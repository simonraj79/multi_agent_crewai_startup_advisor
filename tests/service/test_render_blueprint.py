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

import re
import unittest
from pathlib import Path

import yaml

BLUEPRINT = Path(__file__).parents[2] / "render.yaml"
PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"

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


#: Anything shaped like an e-mail address. Deliberately crude and deliberately
#: applied to the WHOLE FILE rather than to parsed values: a manifest comment
#: naming an address publishes it exactly as loudly as a `value:` does, and the
#: last one was half in a comment.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class ManifestPublishesNoPersonalDataTests(unittest.TestCase):
    """Audit L4: this repository is PUBLIC and the manifest is committed.

    `USER_SPEND_CAP_EXEMPT` carried the owner's e-mail address as a literal
    from the day the per-account cap landed (2026-09-07) until the same day's
    audit. It is not a credential - it grants nothing, and knowing it does not
    let anybody spend - which is exactly why it was easy to write down and easy
    to leave. What it does is publish a personal address to everyone who reads
    the deployment manifest of a public repository, for a value the running
    service reads out of the environment and never needs legible here.

    `sync: false` is the answer rather than deletion: the key stays declared,
    Render keeps the dashboard value an applied Blueprint already has, and a
    fresh Blueprint prompts for it. An opaque Better Auth user id is better
    still and this test accepts one, because a user id is not an address.

    The two service-level assertions are separate on purpose. The first is the
    finding; the second is the class of thing the finding belongs to, and it is
    the one that fails when somebody writes a support address into a comment.
    """

    def test_l4_the_account_exemption_is_withheld_rather_than_committed(self) -> None:
        entry = None
        for service in services().values():
            for candidate in service.get("envVars", []) or []:
                if candidate.get("key") == "USER_SPEND_CAP_EXEMPT":
                    entry = candidate
        self.assertIsNotNone(entry, "render.yaml declares no USER_SPEND_CAP_EXEMPT")
        assert entry is not None  # for the type checker; the assert above is the test

        self.assertIs(
            entry.get("sync"),
            False,
            "USER_SPEND_CAP_EXEMPT names a person; it is entered in the Render "
            "dashboard, never committed to a public manifest (audit L4)",
        )
        self.assertNotIn(
            "value",
            entry,
            "a `sync: false` entry carrying a literal value publishes it anyway",
        )

    def test_l4_no_env_var_value_anywhere_is_an_e_mail_address(self) -> None:
        for name, service in services().items():
            for entry in service.get("envVars", []) or []:
                value = str(entry.get("value", ""))
                with self.subTest(service=name, key=entry.get("key")):
                    self.assertIsNone(
                        EMAIL.search(value),
                        f"{entry.get('key')} publishes an e-mail address",
                    )

    def test_l4_the_whole_manifest_names_no_e_mail_address(self) -> None:
        """Comments included, because a comment is published too."""

        found = EMAIL.findall(BLUEPRINT.read_text(encoding="utf-8"))
        self.assertEqual(found, [], f"render.yaml names {found}")


class PackageMetadataPublishesNoAddressTests(unittest.TestCase):
    """The second half of L4, and the one that also reaches PyPI metadata.

    `pyproject.toml`'s `authors` carried `name` AND `email`. PEP 621 makes the
    address optional, every wheel built from this tree embeds whatever is here,
    and attribution - which is what the field is for - is complete with the name
    alone. Asserted over the whole file rather than over the parsed `authors`
    table so that `maintainers`, a URL or a comment cannot reintroduce one.
    """

    def test_l4_pyproject_names_an_author_and_no_address(self) -> None:
        text = PYPROJECT.read_text(encoding="utf-8")

        found = EMAIL.findall(text)
        self.assertEqual(found, [], f"pyproject.toml names {found}")
        # The name is the point: dropping the address must not drop attribution.
        self.assertIn('name = "Simon Raj"', text)


if __name__ == "__main__":
    unittest.main()
