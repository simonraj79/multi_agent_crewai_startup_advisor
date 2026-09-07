"""Audit M13 (the log-export half) - the export is bounded and off the loop.

`GET /api/runs/{id}/logs` joined EVERY frame of a run into one string inline in
an `async def`, and for `format=zip` then DEFLATEd it in a `BytesIO` there too.
Two things make that worse than it sounds. `all_frames` pages the DATABASE, not
the 2,000-frame in-memory ring, so the string is the size of the run's whole
durable history rather than of its tail; and only `POST .../runs` carries a
rate limit, so nothing bounded how often an owner could ask for it. Both halves
held the interpreter lock, which is the same failure mode as audit C1 reached
by a different route.

Three properties are pinned here, and the third is the one a unit test would
normally be unable to see:

* the export stops at `MAX_EXPORT_FRAMES`;
* the NDJSON path never materialises the whole run - `all_frames` is booby
  trapped and the export still works;
* the ZIP is built where there is no running event loop.

Everything runs against the synthetic registry: in-memory SQLite, the
deterministic double, no model and no network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import unittest
from unittest.mock import patch
import zipfile


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AuditM13LogExportTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        self.registry = self.client.app.state.run_registry
        self.run_id = self._finished_run()

    def _finished_run(self) -> str:
        run_id = self.client.post(
            "/api/sessions/audit-m13/runs",
            json={"workflow_id": "brief-flow", "inputs": {"topic": "logs"}},
        ).json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        return run_id

    def _frame_count(self) -> int:
        return len(self.registry.all_frames(self.run_id))

    # ------------------------------------------------------------------ cap

    def test_m13_the_ndjson_export_stops_at_the_cap(self) -> None:
        total = self._frame_count()
        self.assertGreater(total, 3, "the run produced too few frames to cap")

        with patch("brief_crew.service.app.MAX_EXPORT_FRAMES", 3):
            body = self.client.get(f"/api/runs/{self.run_id}/logs").content

        lines = [line for line in body.split(b"\n") if line]
        self.assertEqual(len(lines), 3)
        # Still well formed: a truncated export is a shorter log, not a broken
        # one, because whoever is reading it is debugging.
        self.assertEqual(json.loads(lines[0])["type"], "frame")

    def test_m13_the_zip_export_stops_at_the_cap_and_says_so(self) -> None:
        self.assertGreater(self._frame_count(), 3)

        with patch("brief_crew.service.app.MAX_EXPORT_FRAMES", 3):
            body = self.client.get(f"/api/runs/{self.run_id}/logs?format=zip").content

        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            frames = archive.read("frames.ndjson").decode("utf-8").splitlines()
            run = json.loads(archive.read("run.json"))

        self.assertEqual(len(frames), 3)
        self.assertEqual(run["frames"]["exported"], 3)
        self.assertTrue(run["frames"]["truncated"])

    def test_m13_an_uncapped_export_is_not_marked_truncated(self) -> None:
        """The flag has to mean something, so it must be able to be false."""
        body = self.client.get(f"/api/runs/{self.run_id}/logs?format=zip").content

        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            run = json.loads(archive.read("run.json"))

        self.assertFalse(run["frames"]["truncated"])
        self.assertEqual(run["frames"]["exported"], self._frame_count())

    def test_m13_the_cap_is_a_constant_and_not_an_environment_knob(self) -> None:
        """A knob is a thing an operator can raise back to the defect.

        It is also the difference between a change that needs a
        `docs/tech-stack.md` section 6 row and one that does not - the canonical
        scan keys on `os.getenv` / `_env_*`, and this must not be found by it.
        """
        import re

        from brief_crew import config

        self.assertIsInstance(config.MAX_EXPORT_FRAMES, int)
        self.assertGreater(config.MAX_EXPORT_FRAMES, 2000)  # over the ring
        source = (
            __import__("pathlib")
            .Path(config.__file__)
            .read_text(encoding="utf-8")
        )
        knob = re.compile(
            r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*"MAX_EXPORT_FRAMES"'
        )
        self.assertIsNone(knob.search(source))

    # --------------------------------------------------------- no full build

    def test_m13_the_ndjson_export_never_materialises_the_whole_run(self) -> None:
        """`all_frames` is the method that joins everything; it must be unused."""

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError(
                "download_logs built the whole run in memory via all_frames"
            )

        with patch.object(self.registry, "all_frames", refuse):
            response = self.client.get(f"/api/runs/{self.run_id}/logs")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.endswith(b"\n"))

    def test_m13_iter_frames_is_a_generator_bounded_across_pages(self) -> None:
        import inspect

        self.assertTrue(inspect.isgeneratorfunction(type(self.registry).iter_frames))
        total = self._frame_count()
        self.assertEqual(len(list(self.registry.iter_frames(self.run_id))), total)
        self.assertEqual(
            len(list(self.registry.iter_frames(self.run_id, limit=2))), 2
        )
        self.assertEqual(
            len(list(self.registry.iter_frames(self.run_id, limit=total + 10))), total
        )

    # ------------------------------------------------------------- off loop

    def test_m13_the_zip_is_built_where_there_is_no_running_event_loop(self) -> None:
        """The direct question, asked directly.

        `run_in_threadpool` puts the DEFLATE on a worker thread, and a worker
        thread has no running loop - so `get_running_loop()` raising IS the
        assertion. On the event loop it would return one.
        """
        seen: list[bool] = []
        real = self.registry.status_payload

        def record(run_id: str):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                seen.append(False)
            else:
                seen.append(True)
            return real(run_id)

        with patch.object(self.registry, "status_payload", record):
            response = self.client.get(f"/api/runs/{self.run_id}/logs?format=zip")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, [False], "the ZIP was built on the event loop")

    # ------------------------------------------------------- unchanged shape

    def test_m13_both_formats_still_return_what_they_always_did(self) -> None:
        ndjson = self.client.get(f"/api/runs/{self.run_id}/logs?format=ndjson")
        self.assertEqual(ndjson.status_code, 200)
        self.assertEqual(ndjson.headers["content-type"], "application/x-ndjson")
        self.assertIn(
            f'filename="run-{self.run_id}.ndjson"',
            ndjson.headers["content-disposition"],
        )

        archive_response = self.client.get(f"/api/runs/{self.run_id}/logs?format=zip")
        self.assertEqual(archive_response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"frames.ndjson", "run.json", "node-metrics.json"},
            )
            run = json.loads(archive.read("run.json"))
            self.assertEqual(run["run_id"], self.run_id)
            self.assertEqual(
                json.loads(archive.read("node-metrics.json")), run["node_usage"]
            )

    def test_m13_an_unknown_format_is_still_refused_before_any_work(self) -> None:
        response = self.client.get(f"/api/runs/{self.run_id}/logs?format=tar")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
