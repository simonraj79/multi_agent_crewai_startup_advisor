"""Audit H5, the second half: the custom tool's transport has a WALL clock.

httpx's ``timeout`` is per read and httpx has no total-request deadline, so a
server that emits one byte just inside the read timeout used to hold the call
open until ``max_response_bytes`` arrived. ``_default_transport`` now bounds
the whole call with the same number the author chose for one read.
"""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest import mock

from brief_crew.builder import tools


class _TricklingResponse:
    """Three chunks, each after a pause that is inside the per-read timeout."""

    status_code = 200

    def __init__(self, pause: float, chunks: int) -> None:
        self._pause = pause
        self._chunks = chunks

    def iter_bytes(self):
        for _ in range(self._chunks):
            time.sleep(self._pause)
            yield b"x"

    def __enter__(self) -> "_TricklingResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _TricklingClient:
    pause = 0.0
    chunks = 0

    def __init__(self, **kwargs: Any) -> None:
        pass

    def stream(self, *args: Any, **kwargs: Any) -> _TricklingResponse:
        return _TricklingResponse(self.pause, self.chunks)

    def __enter__(self) -> "_TricklingClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class TransportDeadlineTests(unittest.TestCase):
    def _call(self, pause: float, chunks: int, timeout: int) -> tuple[int, str]:
        import httpx

        client = type("Client", (_TricklingClient,), {"pause": pause, "chunks": chunks})
        with mock.patch.object(httpx, "Client", client):
            return tools._default_transport(
                "GET", "https://api.example.test/x", {}, None, timeout, 1_000_000
            )

    def test_a_trickle_that_outlives_the_timeout_is_abandoned(self) -> None:
        # Each read is 0.4 s, inside a 1 s read timeout; the whole call is not.
        started = time.monotonic()
        with self.assertRaises(tools._ResponseTooLarge) as caught:
            self._call(pause=0.4, chunks=6, timeout=1)
        elapsed = time.monotonic() - started
        self.assertIsInstance(caught.exception, tools._ResponseTooSlow)
        self.assertIn("longer than 1s", str(caught.exception))
        self.assertLess(elapsed, 2.0, f"the call ran {elapsed:.2f}s past a 1 s deadline")

    def test_a_fast_response_is_untouched(self) -> None:
        status, text = self._call(pause=0.0, chunks=3, timeout=1)
        self.assertEqual((status, text), (200, "xxx"))

    def test_the_slow_refusal_is_a_failed_envelope_not_a_raise(self) -> None:
        """The subclass is what keeps the tool's own `except` catching it."""

        self.assertTrue(issubclass(tools._ResponseTooSlow, tools._ResponseTooLarge))


if __name__ == "__main__":
    unittest.main()
