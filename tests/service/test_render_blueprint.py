"""`render.yaml` must not leave a build-time variable to be remembered.

This exists because of a measured production failure on 2026-09-01, not a
hypothetical. `VITE_API_URL` was declared `sync: false` - "fill this in by hand
once the API's URL is known" - and on the live studio service it was never
filled in.

Vite INLINES `import.meta.env.VITE_API_URL` at build time, so an empty value
ships a bundle whose `baseUrl` is `''`. Every API call then resolves against the
studio's OWN origin, hits the SPA history fallback in `frontend/server/
index.ts`, and comes back `200 text/html`. Measured on the deployed site:

    GET https://agentic-crew-ai-studio.onrender.com/api/workflows -> 200, HTML

The console could not tell that from "the backend is offline" and played a
scripted demonstration run instead - a complete fabricated validation with a
verdict and a dollar cost. An operator reported it as a missing report.

The failure mode is what makes this worth a test: nothing was broken, nothing
logged, the build was green, and the service was serving. The only signal was a
convincing fake. Deployment trap 2 in `docs/gotchas-and-insights.md` names this
exact hazard - "getting it wrong is silent" - and the trap was documented and
still walked into, because documentation cannot fail a build.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

BLUEPRINT = Path(__file__).parents[2] / "render.yaml"

#: Build-time variables. Their values are baked into a bundle, so an unset one
#: cannot be corrected at runtime and cannot report itself from inside the
#: service - it can only be observed by watching where the browser sends its
#: requests. Anything in this set must carry a literal `value:` here.
BUILD_TIME_KEYS = frozenset({"VITE_API_URL"})


def services() -> dict[str, dict]:
    document = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    return {service["name"]: service for service in document["services"]}


class BlueprintDeclaresBuildTimeVariablesTests(unittest.TestCase):
    def test_every_build_time_variable_has_a_literal_value(self) -> None:
        for name, service in services().items():
            for entry in service.get("envVars", []) or []:
                key = entry.get("key")
                if key not in BUILD_TIME_KEYS:
                    continue
                with self.subTest(service=name, key=key):
                    self.assertNotIn(
                        "sync",
                        entry,
                        f"{key} is baked into the bundle at build time; "
                        "`sync: false` makes it a manual step, and that step "
                        "was missed on the live service",
                    )
                    value = entry.get("value")
                    self.assertTrue(
                        value and str(value).strip(),
                        f"{key} must carry a non-empty value",
                    )

    def test_the_api_url_is_a_full_origin_with_a_scheme(self) -> None:
        """It is a fetch prefix AND the base of `new URL(...)` for the socket.

        A bare hostname resolves as a RELATIVE path, which breaks /ws while
        leaving ordinary requests looking almost right - the worst of both.
        """
        entry = self._entry("agentic-crew-ai-studio", "VITE_API_URL")
        value = str(entry["value"]).strip()

        self.assertTrue(value.startswith("https://"), value)
        self.assertFalse(value.endswith("/"), "a trailing slash doubles up in the path")

    def test_the_api_url_and_the_auth_url_name_different_origins(self) -> None:
        """A copy-paste that pointed both at one service would reproduce the
        exact defect this file exists to prevent - and would look correct."""
        api = str(self._entry("agentic-crew-ai-studio", "VITE_API_URL")["value"])
        auth = str(self._entry("agentic-crew-ai-api", "AUTH_BASE_URL")["value"])

        self.assertNotEqual(api.strip(), auth.strip())

    def _entry(self, service_name: str, key: str) -> dict:
        for entry in services()[service_name].get("envVars", []) or []:
            if entry.get("key") == key:
                return entry
        self.fail(f"{service_name} declares no {key}")


if __name__ == "__main__":
    unittest.main()
