"""Audit L1 - the bearer token must not survive into the access log.

The WebSocket handshake carries the 15-minute JWT as a **query parameter**, and
that is forced rather than chosen: the browser WebSocket API cannot set a
header on a handshake, so `Authorization` is unavailable exactly there. uvicorn
writes the request line verbatim at its default access-log level, so every
handshake wrote `GET /ws?...&access_token=eyJ...` into Render's log stream and
into any drain attached to it. Anyone with log read access held a working API
credential for the rest of its lifetime - and the run id beside it, which after
audit H1 was the other half of a complete attack.

What this closes is the *value*, not the mechanism. Two better answers are
outside this module and are named in the filter's own docstring: run uvicorn
with `--no-access-log`, and carry the token in `Sec-WebSocket-Protocol`, which
the browser API can set.

No network, no model, no app needed for the filter itself: a `LogRecord` is
built by hand, which is what a log filter actually sees.
"""

from __future__ import annotations

import importlib.util
import logging
import unittest


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# uvicorn's own access format and its own argument tuple:
#   '%s - "%s %s HTTP/%s" %d' % (client, method, full_path, version, status)
UVICORN_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
HANDSHAKE_PATH = "/ws?session_id=s&run_id=r&access_token=eyJabc"


def access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=UVICORN_ACCESS_FORMAT,
        args=("127.0.0.1:52000", "GET", path, "1.1", 200),
        exc_info=None,
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AuditL1AccessLogFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        from brief_crew.service.app import _StripQueryCredentials

        self.filter = _StripQueryCredentials()

    def test_l1_the_handshake_token_is_replaced_in_the_record(self) -> None:
        record = access_record(HANDSHAKE_PATH)

        self.assertTrue(self.filter.filter(record))

        rendered = record.getMessage()
        self.assertIn("access_token=***", rendered)
        self.assertNotIn("eyJabc", rendered)
        # The rest of the line survives: an access log that loses the path is
        # not an access log.
        self.assertIn("/ws?session_id=s&run_id=r", rendered)
        self.assertIn("GET", rendered)
        self.assertIn("200", rendered)

    def test_l1_a_record_without_the_parameter_is_untouched(self) -> None:
        record = access_record("/api/runs/1c1b6f1e-0000-4000-8000-000000000000")
        before = record.getMessage()

        self.assertTrue(self.filter.filter(record))

        self.assertEqual(record.getMessage(), before)

    def test_l1_the_filter_never_drops_a_record(self) -> None:
        """Returning False would delete the access log rather than redact it."""
        for path in (HANDSHAKE_PATH, "/healthz"):
            with self.subTest(path=path):
                self.assertTrue(self.filter.filter(access_record(path)))

    def test_l1_a_token_in_any_position_and_shape_is_caught(self) -> None:
        cases = (
            ("/ws?access_token=eyJ.abc-def_ghi&after=0", "/ws?access_token=***&after=0"),
            ("/ws?a=1&access_token=eyJ", "/ws?a=1&access_token=***"),
            # Two of them, which a naive non-global substitution would half-miss.
            (
                "/ws?access_token=one&x=2&access_token=two",
                "/ws?access_token=***&x=2&access_token=***",
            ),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                record = access_record(path)
                self.filter.filter(record)
                self.assertIn(expected, record.getMessage())

    def test_l1_an_already_formatted_message_is_scrubbed_too(self) -> None:
        """Some loggers format before they log; `msg` must not be a bypass."""
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f'127.0.0.1 - "GET {HANDSHAKE_PATH} HTTP/1.1" 200',
            args=None,
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertNotIn("eyJabc", record.getMessage())

    def test_l1_a_non_string_argument_is_left_alone(self) -> None:
        """The status code is an int and must stay one, or the format explodes."""
        record = access_record(HANDSHAKE_PATH)
        self.filter.filter(record)
        assert isinstance(record.args, tuple)
        self.assertEqual(record.args[-1], 200)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AuditL1FilterInstallationTests(unittest.TestCase):
    """It has to be ON, and on exactly once."""

    def setUp(self) -> None:
        from brief_crew.service.app import _StripQueryCredentials

        self.cls = _StripQueryCredentials
        access_log = logging.getLogger("uvicorn.access")
        existing = list(access_log.filters)
        self.addCleanup(setattr, access_log, "filters", existing)
        access_log.filters = [
            item for item in existing if not isinstance(item, self.cls)
        ]

    def _installed(self) -> list[logging.Filter]:
        return [
            item
            for item in logging.getLogger("uvicorn.access").filters
            if isinstance(item, self.cls)
        ]

    def test_l1_creating_an_app_installs_the_filter(self) -> None:
        from brief_crew.service.app import create_app

        self.assertEqual(self._installed(), [])
        create_app(synthetic=True)
        self.assertEqual(len(self._installed()), 1)

    def test_l1_building_many_apps_installs_it_only_once(self) -> None:
        """This suite builds hundreds of apps in one process."""
        from brief_crew.service.app import create_app

        for _ in range(5):
            create_app(synthetic=True)

        self.assertEqual(len(self._installed()), 1)


if __name__ == "__main__":
    unittest.main()
