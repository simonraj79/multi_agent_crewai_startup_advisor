"""`GET /api/builder/models` - plan 05 criterion 8, and C3 on the wire.

Three claims.

**It is the registry verbatim.** Every row, both price columns, the ceiling and
the two presets, checked against `config.MODEL_REGISTRY` at run time rather than
transcribed - transcribing would make this test agree with the endpoint for
exactly as long as both were copied from the same place, which is no check at
all.

**It is unauthenticated**, and that is asserted against an app which REQUIRES
auth. On a synthetic app with no auth server every route answers anonymously and
a 200 would prove nothing. The reason it must be open is the same one
`/vocabulary` gives: this describes the BUILD, not anybody's data, and the
inspector's model picker has to resolve before the console's three-phase auth
gate does or it is empty for the whole of a sign-in.

**The conditional GET is actually conditional.** The graph endpoint shipped an
`ETag` that was written and never read for a while - a fresh 200 and the whole
descriptor again for a client carrying back the exact tag the server had just
issued. That is decoration, not caching, and it looks implemented in a review.
The roster is a better candidate than the graph: it is fixed for the life of a
deploy and every page load fetches it.

No cost: a synthetic app over in-memory SQLite, and GETs.
"""

from __future__ import annotations

import unittest

from brief_crew import config as project_config
from tests.service.builder_auth import BuilderAuthCase

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

PATH = "/api/builder/models"


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ModelsPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.response = self.client.get(PATH)
        self.assertEqual(self.response.status_code, 200, self.response.text)
        self.payload = self.response.json()

    def test_it_carries_exactly_c3s_top_level_keys(self) -> None:
        self.assertEqual(
            sorted(self.payload),
            sorted(
                [
                    "schema",
                    "generated_at",
                    "source",
                    "ceiling_usd_per_m_input",
                    "presets",
                    "models",
                ]
            ),
        )

    def test_the_rows_are_the_registry_in_the_registrys_own_order(self) -> None:
        """Order matters: `data/models.json` lists the roster's own ranking.

        Sorting it here would make the picker's first suggestion depend on a
        slug's alphabet rather than on why the model is on the roster.
        """

        self.assertEqual(
            [row["id"] for row in self.payload["models"]],
            [model.id for model in project_config.MODEL_REGISTRY],
        )

    def test_every_row_carries_every_c3_field(self) -> None:
        for row in self.payload["models"]:
            with self.subTest(model=row["id"]):
                self.assertEqual(
                    sorted(row),
                    sorted(
                        [
                            "id",
                            "name",
                            "provider",
                            "context_window",
                            "supports_tools",
                            "supports_vision",
                            "supports_json_mode",
                            "supports_reasoning",
                            "cost_in",
                            "cost_out",
                            "cost_in_max_endpoint",
                            "speed_tier",
                            "recommended_for",
                        ]
                    ),
                )

    def test_both_price_columns_are_served(self) -> None:
        """The one that prices a run AND the one that gates admission.

        Reporting only `cost_in` is what let a `:batch` price be read as a
        headline once already; reporting only the maximum would hide what a run
        actually costs. The escalation preset is the row where the two disagree
        most - $0.75 headline, $1.35 on its two `priority` endpoints.
        """

        by_id = {row["id"]: row for row in self.payload["models"]}
        escalation = by_id["google/gemini-3.8-flash"]
        self.assertEqual(escalation["cost_in"], 0.75)
        self.assertEqual(escalation["cost_in_max_endpoint"], 1.35)

    def test_the_presets_resolve_to_rows_and_keep_their_variants(self) -> None:
        """`:nitro` survives, and the survival is the useful part.

        Nitro routes on speed rather than price, so the cheap preset's published
        rate is a floor - which is exactly what the picker has to be able to
        explain when the meter shows more than the headline implies. Stripping
        the variant here would delete the evidence.
        """

        presets = self.payload["presets"]
        self.assertEqual(presets["cheap"], "google/gemini-3.5-flash-lite:nitro")
        ids = {row["id"] for row in self.payload["models"]}
        for tier, spelling in presets.items():
            with self.subTest(tier=tier):
                base = spelling.removeprefix("openrouter/").split(":", 1)[0]
                self.assertIn(base, ids)

    def test_the_ceiling_is_the_one_config_enforces(self) -> None:
        self.assertEqual(
            self.payload["ceiling_usd_per_m_input"], project_config.MODEL_PRICE_CEILING_IN
        )

    def test_no_row_is_over_the_ceiling_it_serves(self) -> None:
        for row in self.payload["models"]:
            with self.subTest(model=row["id"]):
                self.assertLessEqual(
                    row["cost_in"], self.payload["ceiling_usd_per_m_input"]
                )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ModelsEtagTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.first = self.client.get(PATH)
        self.etag = self.first.headers["ETag"]

    def test_a_200_carries_an_etag(self) -> None:
        self.assertEqual(self.first.status_code, 200)
        self.assertTrue(self.etag.startswith('"') and self.etag.endswith('"'))

    def test_the_exact_tag_gives_304_and_an_empty_body(self) -> None:
        response = self.client.get(PATH, headers={"If-None-Match": self.etag})
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")

    def test_the_304_repeats_the_tag(self) -> None:
        """RFC 9110 requires it, so a cache can refresh its own freshness record."""

        response = self.client.get(PATH, headers={"If-None-Match": self.etag})
        self.assertEqual(response.headers["ETag"], self.etag)

    def test_a_weakened_tag_still_matches(self) -> None:
        """A proxy is entitled to weaken a tag in transit.

        Refusing the match then would silently turn every 304 back into a 200
        with nothing in the logs to say why - the same trap `get_graph` records.
        """

        response = self.client.get(PATH, headers={"If-None-Match": f"W/{self.etag}"})
        self.assertEqual(response.status_code, 304)

    def test_a_list_of_tags_matches_if_any_of_them_does(self) -> None:
        response = self.client.get(
            PATH, headers={"If-None-Match": f'"stale-one", {self.etag}'}
        )
        self.assertEqual(response.status_code, 304)

    def test_a_star_matches_any_representation(self) -> None:
        response = self.client.get(PATH, headers={"If-None-Match": "*"})
        self.assertEqual(response.status_code, 304)

    def test_a_stale_tag_gives_the_whole_roster_back(self) -> None:
        response = self.client.get(PATH, headers={"If-None-Match": '"not-this-one"'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["models"]), len(project_config.MODEL_REGISTRY))

    def test_a_malformed_header_degrades_to_a_200(self) -> None:
        """A bad cache header must never fail a request."""

        response = self.client.get(PATH, headers={"If-None-Match": "W/ , , ,"})
        self.assertEqual(response.status_code, 200)

    def test_the_tag_is_the_hash_of_the_registry_FILE(self) -> None:
        """Of the file, not of the serialised body, and the difference matters.

        The file is what `refresh_models.py` rewrites and what a commit shows a
        diff of, so a tag taken from it moves exactly when the roster moves. A
        hash of the response would also move when a key order changed, inventing
        a cache miss out of a refactor.
        """

        import hashlib

        digest = hashlib.sha256(
            project_config.MODEL_REGISTRY_PATH.read_bytes()
        ).hexdigest()
        self.assertEqual(self.etag, f'"{digest}"')

    def test_the_graphs_tag_never_satisfies_this_one(self) -> None:
        """Two resources, two tags. A shared one would serve the wrong body."""

        graph = self.client.get("/api/workflows/idea-validator/graph")
        response = self.client.get(PATH, headers={"If-None-Match": graph.headers["ETag"]})
        self.assertEqual(response.status_code, 200)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ModelsAreUnauthenticatedTests(BuilderAuthCase):
    """Asserted against an app that REQUIRES auth, or it proves nothing."""

    def test_it_answers_200_with_no_bearer_token(self) -> None:
        response = self.client.get(PATH)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            len(response.json()["models"]), len(project_config.MODEL_REGISTRY)
        )

    def test_the_conditional_get_is_open_too(self) -> None:
        """A 304 path behind an auth gate would be a cache that only signed-in
        users get, which is the sort of asymmetry nobody notices until a CDN
        does."""

        etag = self.client.get(PATH).headers["ETag"]
        response = self.client.get(PATH, headers={"If-None-Match": etag})
        self.assertEqual(response.status_code, 304)

    def test_a_route_that_reads_data_still_refuses_the_same_caller(self) -> None:
        """The control: proves the auth gate is genuinely armed on this app."""

        response = self.client.get("/api/builder/workflows")
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
