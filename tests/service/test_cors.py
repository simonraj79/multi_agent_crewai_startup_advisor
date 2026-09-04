"""Cross-origin access for the FastAPI service.

In development none of this is reachable: Vite serves the app and proxies
`/api` and `/ws` into this process (frontend/vite.config.ts), so every request
is same-origin and the browser never asks for permission. In production the Vue
app is a separate static site on its own origin (render.yaml:
agentic-crew-ai-web) calling the API through VITE_API_URL, so every request is
cross-origin and the browser discards the response unless the API names the
caller. These tests pin both halves of that: what an allowed origin gets, and
what everyone else - including the default configuration - does not.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import os
import subprocess
import sys
import unittest
from typing import Any
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

ALLOWED_ORIGIN = "https://studio.example.com"
OTHER_ORIGIN = "https://not-the-studio.example.com"


class CorsOriginParsingTests(unittest.TestCase):
    """The env value is parsed and validated in config.py, with no FastAPI."""

    def setUp(self) -> None:
        from brief_crew import config

        self.config = config

    def test_default_is_no_cross_origin_access(self) -> None:
        # The unset env var reads as "", and "" must mean nobody - not
        # everybody. Same-origin traffic does not consult this list at all.
        self.assertEqual(self.config._parse_cors_allow_origins(""), ())
        self.assertEqual(self.config._parse_cors_allow_origins("  ,  ,"), ())

    def test_origins_are_parsed_normalised_and_deduplicated(self) -> None:
        parsed = self.config._parse_cors_allow_origins(
            " https://studio.example.com , HTTP://LocalHost:5173,"
            "https://studio.example.com "
        )
        # Scheme and host are case-insensitive by specification and a browser
        # always sends them lowercased, so normalising them changes nothing an
        # operator meant - unlike a path or a trailing slash, which are refused.
        self.assertEqual(
            parsed, ("https://studio.example.com", "http://localhost:5173")
        )

    def test_trailing_slash_is_refused_with_the_corrected_value(self) -> None:
        # The classic misconfiguration. Starlette compares the Origin header
        # against these strings exactly and no browser sends a trailing slash,
        # so accepting it would ship a rule that silently matches nothing.
        with self.assertRaises(ValueError) as caught:
            self.config._parse_cors_allow_origins("https://studio.example.com/")
        message = str(caught.exception)
        self.assertIn("trailing slash", message)
        self.assertIn("write https://studio.example.com instead", message)

    def test_a_url_is_refused_with_the_corrected_value(self) -> None:
        for value in (
            "https://studio.example.com/app",
            "https://studio.example.com?x=1",
            "https://studio.example.com#frag",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    self.config._parse_cors_allow_origins(value)
                self.assertIn(
                    "write https://studio.example.com instead", str(caught.exception)
                )

    def test_non_origins_are_refused(self) -> None:
        for value, expected in (
            ("studio.example.com", "is not an origin"),
            ("//studio.example.com", "is not an origin"),
            ("ftp://studio.example.com", "is not an origin"),
            ("file:///tmp", "is not an origin"),
            ("https://", "is not an origin"),
            ("https://studio.example.com:not-a-port", "invalid port"),
            ("https://user:secret@studio.example.com", "carries credentials"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    self.config._parse_cors_allow_origins(value)
                self.assertIn(expected, str(caught.exception))
                self.assertIn("CORS_ALLOW_ORIGINS", str(caught.exception))

    def test_wildcard_is_accepted_alone_and_refused_alongside_names(self) -> None:
        # "*" stays available for an operator who deliberately wants an open
        # API - safe only because credentials are off. Mixing it with named
        # origins is refused because the names would be dead text.
        self.assertEqual(self.config._parse_cors_allow_origins("*"), ("*",))
        with self.assertRaises(ValueError) as caught:
            self.config._parse_cors_allow_origins("*,https://studio.example.com")
        self.assertIn("dead text", str(caught.exception))

    def test_credentials_are_off_so_the_wildcard_stays_survivable(self) -> None:
        self.assertFalse(self.config.CORS_ALLOW_CREDENTIALS)

    def test_the_constant_is_whatever_the_environment_says(self) -> None:
        self.assertEqual(
            self.config.CORS_ALLOW_ORIGINS,
            self.config._parse_cors_allow_origins(
                os.environ.get("CORS_ALLOW_ORIGINS", "")
            ),
        )

    def test_a_malformed_value_is_refused_at_import(self) -> None:
        """Startup, not first request: a config that cannot match never boots.

        Run in a subprocess, and by file path rather than through the package,
        for two reasons: reloading `brief_crew.config` in place would hand every
        module that already imported a constant from it a stale object, and
        `brief_crew/__init__.py` loads `.env` with `override=True`, which would
        let a developer's own file decide what this test measures.
        """
        environment = dict(os.environ)
        environment["CORS_ALLOW_ORIGINS"] = "https://studio.example.com/"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('probe', sys.argv[1])\n"
                "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n",
                self.config.__file__,
            ],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("trailing slash", completed.stderr)
        self.assertIn("write https://studio.example.com instead", completed.stderr)


@contextmanager
def cors_client(origins):
    """A synthetic-mode client whose app was built against `origins`."""
    from fastapi.testclient import TestClient

    from brief_crew import config as project_config
    from brief_crew.service.app import create_app

    with patch.object(project_config, "CORS_ALLOW_ORIGINS", tuple(origins)):
        client = TestClient(create_app(synthetic=True))
    try:
        yield client
    finally:
        client.close()


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class CorsMiddlewareTests(unittest.TestCase):
    def test_preflight_from_an_allowed_origin_is_granted(self) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            response = client.options(
                "/api/sessions/session-cors/runs",
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], ALLOWED_ORIGIN
        )
        allowed_methods = response.headers["access-control-allow-methods"]
        self.assertEqual(
            [method.strip() for method in allowed_methods.split(",")],
            ["GET", "POST", "OPTIONS"],
        )
        self.assertIn("Content-Type", response.headers["access-control-allow-headers"])
        # Vary: Origin, or a shared cache would serve one origin's answer to
        # another.
        self.assertIn("Origin", response.headers["vary"])
        # No ambient credential exists to grant, so none is advertised.
        self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_preflight_for_an_ungranted_method_is_refused(self) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            response = client.options(
                "/api/sessions/session-cors/runs",
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "DELETE",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("method", response.text)

    def test_simple_request_from_an_allowed_origin_carries_the_allow_header(
        self,
    ) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            response = client.get("/api/workflows", headers={"Origin": ALLOWED_ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], ALLOWED_ORIGIN
        )
        self.assertIn("Origin", response.headers["vary"])

    def test_an_unlisted_origin_gets_no_allow_header(self) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            simple = client.get("/api/workflows", headers={"Origin": OTHER_ORIGIN})
            preflight = client.options(
                "/api/sessions/session-cors/runs",
                headers={
                    "Origin": OTHER_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
        # The body is still served - CORS is enforced in the browser, not here -
        # but without the header the browser will not hand it to the page.
        self.assertEqual(simple.status_code, 200)
        self.assertNotIn("access-control-allow-origin", simple.headers)
        self.assertEqual(preflight.status_code, 400)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_the_default_configuration_admits_nobody(self) -> None:
        with cors_client([]) as client:
            simple = client.get("/api/workflows", headers={"Origin": ALLOWED_ORIGIN})
            preflight = client.options(
                "/api/sessions/session-cors/runs",
                headers={
                    "Origin": ALLOWED_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                },
            )
            same_origin = client.get("/api/workflows")
        self.assertNotIn("access-control-allow-origin", simple.headers)
        self.assertEqual(preflight.status_code, 400)
        # Same-origin traffic - the Vite proxy, curl, the health checker - is
        # untouched by any of this.
        self.assertEqual(same_origin.status_code, 200)
        self.assertNotIn("access-control-allow-origin", same_origin.headers)

    def test_etag_is_exposed_to_cross_origin_readers_of_the_graph(self) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            response = client.get(
                "/api/workflows/idea-validator/graph",
                headers={"Origin": ALLOWED_ORIGIN},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["etag"])
        # ETag is not on the CORS response-header safelist, so without this the
        # graph version is invisible to a cross-origin client.
        exposed = [
            header.strip()
            for header in response.headers["access-control-expose-headers"].split(",")
        ]
        self.assertIn("ETag", exposed)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class WebsocketOriginTests(unittest.TestCase):
    """`/ws` IS governed by `CORS_ALLOW_ORIGINS` now (D-01-7).

    This class replaces `test_the_websocket_handshake_is_not_governed_by_cors`,
    which asserted the opposite and passed: a page on any origin could open the
    socket and stream any run whose `run_id` and `session_id` it could name.
    That was survivable for an OWNED run, which is 4404 to everybody but its
    owner, and not for an unowned one - every run on an auth-off checkout and
    every run in `SYNTHETIC` mode, which is the configuration the whole judging
    round ran in.

    The pin is flipped deliberately rather than deleted: the property it
    documented is now the property that must NOT hold.
    """

    @staticmethod
    def _run(client: Any) -> tuple[str, int]:
        created = client.post(
            "/api/sessions/session-ws-cors/runs",
            json={"workflow_id": "brief-flow", "inputs": {"topic": "cors"}},
        )
        run_id = created.json()["run_id"]
        client.app.state.run_registry.wait(run_id, timeout=2)
        last_seq = client.get(f"/api/runs/{run_id}").json()["frames"]["last_seq"]
        return run_id, last_seq

    def _socket(self, client: Any, run_id: str, last_seq: int, **kwargs: Any) -> Any:
        return client.websocket_connect(
            f"/ws?session_id=session-ws-cors&run_id={run_id}&after={last_seq}",
            **kwargs,
        )

    def test_a_foreign_origin_is_refused_before_anything_is_streamed(self) -> None:
        from starlette.websockets import WebSocketDisconnect

        from brief_crew.config import WS_ORIGIN_REFUSED_CLOSE_CODE

        with cors_client([ALLOWED_ORIGIN]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(
                client, run_id, last_seq, headers={"Origin": OTHER_ORIGIN}
            ) as websocket:
                websocket.send_json({"type": "ping"})
                with self.assertRaises(WebSocketDisconnect) as caught:
                    websocket.receive_json()
        self.assertEqual(caught.exception.code, WS_ORIGIN_REFUSED_CLOSE_CODE)
        self.assertEqual(caught.exception.reason, "origin not allowed")

    def test_an_allowed_origin_still_streams(self) -> None:
        with cors_client([ALLOWED_ORIGIN]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(
                client, run_id, last_seq, headers={"Origin": ALLOWED_ORIGIN}
            ) as websocket:
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")

    def test_a_handshake_with_no_origin_header_is_a_non_browser_and_is_served(
        self,
    ) -> None:
        """The probe CLAUDE.md documents, and every server-side consumer.

        A browser always sends `Origin` on a handshake, so its absence is
        positive evidence the caller is not a page. Refusing it would break
        every non-browser client to defend against a threat none of them is.
        """

        with cors_client([ALLOWED_ORIGIN]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(client, run_id, last_seq) as websocket:
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")

    def test_a_same_origin_handshake_is_served_with_the_empty_default_list(
        self,
    ) -> None:
        """The empty default must not mean "no console".

        Local development and the E2E harness both reach this service through a
        Vite proxy that forwards the page's own `Host`, so `Origin` and `Host`
        agree and no configuration is needed. A cross-origin deployment names
        its origins - `render.yaml` does.
        """

        with cors_client([]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(
                client, run_id, last_seq, headers={"Origin": "http://testserver"}
            ) as websocket:
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")

    def test_a_foreign_origin_is_refused_with_the_empty_default_list(self) -> None:
        from starlette.websockets import WebSocketDisconnect

        from brief_crew.config import WS_ORIGIN_REFUSED_CLOSE_CODE

        with cors_client([]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(
                client, run_id, last_seq, headers={"Origin": OTHER_ORIGIN}
            ) as websocket:
                websocket.send_json({"type": "ping"})
                with self.assertRaises(WebSocketDisconnect) as caught:
                    websocket.receive_json()
        self.assertEqual(caught.exception.code, WS_ORIGIN_REFUSED_CLOSE_CODE)

    def test_the_wildcard_opens_the_socket_to_everyone_as_it_does_the_api(
        self,
    ) -> None:
        with cors_client(["*"]) as client:
            run_id, last_seq = self._run(client)
            with self._socket(
                client, run_id, last_seq, headers={"Origin": OTHER_ORIGIN}
            ) as websocket:
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")


class WebsocketOriginPredicateTests(unittest.TestCase):
    """The rule itself, with no FastAPI - `config.websocket_origin_allowed`."""

    def setUp(self) -> None:
        from brief_crew import config

        self.config = config

    def _allowed(self, origin, *, host=None, origins=(ALLOWED_ORIGIN,)):
        with patch.object(self.config, "CORS_ALLOW_ORIGINS", tuple(origins)):
            return self.config.websocket_origin_allowed(origin, host=host)

    def test_a_missing_header_is_allowed_and_an_empty_one_is_not(self) -> None:
        self.assertTrue(self._allowed(None))
        # A present-but-blank header is not a non-browser client; something
        # sent the header and it names nothing.
        self.assertFalse(self._allowed(""))
        self.assertFalse(self._allowed("   "))

    def test_null_is_refused(self) -> None:
        """A sandboxed iframe, a `file://` page, some redirect chains."""

        self.assertFalse(self._allowed("null"))
        self.assertFalse(self._allowed("NULL"))

    def test_the_list_is_matched_after_the_same_normalisation_the_api_uses(
        self,
    ) -> None:
        self.assertTrue(self._allowed("https://studio.example.com"))
        self.assertTrue(self._allowed("HTTPS://Studio.Example.COM"))
        self.assertFalse(self._allowed(OTHER_ORIGIN))

    def test_a_value_that_is_not_an_origin_at_all_is_refused(self) -> None:
        for junk in (
            "studio.example.com",
            "https://studio.example.com/x",
            "javascript:",
        ):
            with self.subTest(junk=junk):
                self.assertFalse(self._allowed(junk, host="studio.example.com"))

    def test_same_origin_is_compared_on_authority_because_host_has_no_scheme(
        self,
    ) -> None:
        self.assertTrue(
            self._allowed("http://localhost:5277", host="localhost:5277", origins=())
        )
        self.assertTrue(
            self._allowed("https://localhost:5277", host="LOCALHOST:5277", origins=())
        )
        # A different port is a different origin, which is the whole point of
        # the rule: the attacker controls Origin and not Host.
        self.assertFalse(
            self._allowed("http://localhost:5278", host="localhost:5277", origins=())
        )
        self.assertFalse(self._allowed("http://localhost:5277", host=None, origins=()))


if __name__ == "__main__":
    unittest.main()
