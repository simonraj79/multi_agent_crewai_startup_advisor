"""The console script's environment switches.

``serve()`` hands uvicorn a factory *by name*, which cannot carry keyword
arguments. Before ``app_from_env`` existed, that meant the registered script
could only ever build the paid runners: starting the service just to look at
the UI would spend real OpenRouter and Firecrawl credit on the first Launch.
These tests pin the switch that makes a no-cost start possible, and the
truthiness rules an operator will actually type.
"""

from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


class TruthyTests(unittest.TestCase):
    def test_accepts_the_spellings_an_operator_writes(self) -> None:
        from brief_crew.service.app import _truthy

        for value in ("1", "true", "TRUE", "True", "yes", "on", "  on  "):
            with self.subTest(value=value):
                self.assertTrue(_truthy(value))

    def test_rejects_everything_else_including_unset(self) -> None:
        from brief_crew.service.app import _truthy

        for value in (None, "", "   ", "0", "false", "no", "off", "synthetic"):
            with self.subTest(value=value):
                self.assertFalse(_truthy(value))


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class AppFromEnvTests(unittest.TestCase):
    def test_synthetic_unset_builds_the_paid_runners(self) -> None:
        from brief_crew.service import app as app_module

        with patch.dict(app_module.os.environ, {}, clear=False) as _env:
            app_module.os.environ.pop("SYNTHETIC", None)
            with patch.object(app_module, "create_app") as create_app:
                app_module.app_from_env()
        create_app.assert_called_once_with(synthetic=False)

    def test_synthetic_set_selects_the_no_cost_doubles(self) -> None:
        from brief_crew.service import app as app_module

        with patch.dict(app_module.os.environ, {"SYNTHETIC": "1"}):
            with patch.object(app_module, "create_app") as create_app:
                app_module.app_from_env()
        create_app.assert_called_once_with(synthetic=True)

    def test_serve_points_uvicorn_at_the_env_aware_factory(self) -> None:
        """A regression guard: pointing back at ``create_app`` silently
        re-breaks the no-cost start, because the string factory drops kwargs."""
        import brief_crew.service.app as app_module

        recorded: dict[str, object] = {}

        class FakeUvicorn:
            @staticmethod
            def run(target: str, **kwargs: object) -> None:
                recorded["target"] = target
                recorded.update(kwargs)

        with patch.dict(
            app_module.os.environ, {"HOST": "0.0.0.0", "PORT": "9111"}
        ):
            with patch.dict("sys.modules", {"uvicorn": FakeUvicorn}):
                app_module.serve()

        self.assertEqual(
            recorded["target"], "brief_crew.service.app:app_from_env"
        )
        self.assertIs(recorded["factory"], True)
        self.assertEqual(recorded["host"], "0.0.0.0")
        self.assertEqual(recorded["port"], 9111)


if __name__ == "__main__":
    unittest.main()
