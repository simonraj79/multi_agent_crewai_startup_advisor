"""The graph `ETag` is honoured, not just emitted.

Closes remaining-work item 14. `get_graph` wrote `ETag: "{graph.version}"` and
nothing anywhere in `src/brief_crew/` ever read `If-None-Match`, so a
conditional GET carrying back the exact tag the server had just issued got a
fresh 200 and the whole 14-node, 16-edge descriptor again. The header was
decoration - the kind that looks implemented in a code review.

The weak-comparison cases are not pedantry. RFC 9110 §13.1.2 requires
``If-None-Match`` to compare weakly, so a proxy that weakened the tag in transit
must still match; getting that wrong silently turns every 304 back into a 200
with nothing in the logs to explain it.
"""

from __future__ import annotations

import unittest

try:  # pragma: no cover - exercised by the skip below
    import fastapi  # noqa: F401

    FASTAPI_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

from brief_crew.service.app import _etag_matches
from brief_crew.service.graph import VALIDATOR_GRAPH


class EtagComparisonTests(unittest.TestCase):
    """`_etag_matches` on its own, where every edge case is cheap to state."""

    ETAG = '"abc123"'

    def test_an_identical_strong_tag_matches(self) -> None:
        self.assertTrue(_etag_matches('"abc123"', self.ETAG))

    def test_a_weakened_tag_still_matches(self) -> None:
        # The whole reason comparison is weak: a proxy may add the W/ prefix in
        # transit, and refusing it would silently disable caching end to end.
        self.assertTrue(_etag_matches('W/"abc123"', self.ETAG))
        self.assertTrue(_etag_matches('w/"abc123"', self.ETAG))

    def test_a_star_matches_any_representation(self) -> None:
        self.assertTrue(_etag_matches("*", self.ETAG))

    def test_a_list_matches_on_any_member(self) -> None:
        # A client that has seen two versions may send both.
        self.assertTrue(_etag_matches('"old", "abc123"', self.ETAG))
        self.assertTrue(_etag_matches('W/"old", W/"abc123"', self.ETAG))

    def test_a_different_tag_does_not_match(self) -> None:
        self.assertFalse(_etag_matches('"nope"', self.ETAG))

    def test_an_unquoted_version_does_not_match(self) -> None:
        # The tag on the wire is quoted; a bare version string is a different
        # value and must not be treated as a hit.
        self.assertFalse(_etag_matches("abc123", self.ETAG))

    def test_whitespace_is_tolerated(self) -> None:
        self.assertTrue(_etag_matches('  W/"abc123"  ', self.ETAG))

    def test_a_malformed_header_degrades_to_no_match(self) -> None:
        # A bad cache header must produce a normal 200, never an error.
        for header in ("", "   ", "garbage", ",,,", 'W/'):
            with self.subTest(header=header):
                self.assertFalse(_etag_matches(header, self.ETAG))


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class GraphConditionalGetTests(unittest.TestCase):
    """The endpoint, over HTTP."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))
        self.path = f"/api/workflows/{VALIDATOR_GRAPH.id}/graph"

    def test_an_unconditional_get_returns_the_graph_and_a_tag(self) -> None:
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["ETag"], f'"{VALIDATOR_GRAPH.version}"')
        self.assertEqual(len(response.json()["nodes"]), 14)

    def test_the_server_s_own_tag_comes_back_304(self) -> None:
        # The exact defect: this returned 200 with the full body.
        etag = self.client.get(self.path).headers["ETag"]
        response = self.client.get(self.path, headers={"If-None-Match": etag})
        self.assertEqual(response.status_code, 304)

    def test_a_304_carries_no_body(self) -> None:
        etag = self.client.get(self.path).headers["ETag"]
        response = self.client.get(self.path, headers={"If-None-Match": etag})
        self.assertEqual(response.content, b"")

    def test_a_304_repeats_the_tag(self) -> None:
        # RFC 9110: a 304 must send the ETag so a cache can refresh its own
        # freshness record from the response.
        etag = self.client.get(self.path).headers["ETag"]
        response = self.client.get(self.path, headers={"If-None-Match": etag})
        self.assertEqual(response.headers["ETag"], etag)

    def test_a_weakened_tag_is_also_a_304(self) -> None:
        etag = self.client.get(self.path).headers["ETag"]
        response = self.client.get(self.path, headers={"If-None-Match": f"W/{etag}"})
        self.assertEqual(response.status_code, 304)

    def test_a_stale_tag_returns_the_graph(self) -> None:
        response = self.client.get(self.path, headers={"If-None-Match": '"stale"'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["nodes"]), 14)

    def test_a_malformed_header_returns_the_graph(self) -> None:
        response = self.client.get(self.path, headers={"If-None-Match": "not-a-tag"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["nodes"]), 14)

    def test_the_brief_graph_gets_its_own_tag(self) -> None:
        from brief_crew.service.graph import BRIEF_GRAPH

        brief = self.client.get(f"/api/workflows/{BRIEF_GRAPH.id}/graph")
        validator = self.client.get(self.path)
        self.assertNotEqual(brief.headers["ETag"], validator.headers["ETag"])

    def test_one_graph_s_tag_does_not_satisfy_the_other(self) -> None:
        # Two workflows, two versions. A cross-hit here would serve the wrong
        # topology as unchanged, which is the worst outcome available.
        from brief_crew.service.graph import BRIEF_GRAPH

        brief_etag = self.client.get(
            f"/api/workflows/{BRIEF_GRAPH.id}/graph"
        ).headers["ETag"]
        response = self.client.get(self.path, headers={"If-None-Match": brief_etag})
        self.assertEqual(response.status_code, 200)

    def test_an_unknown_workflow_is_still_404_with_a_tag_present(self) -> None:
        response = self.client.get(
            "/api/workflows/nope/graph", headers={"If-None-Match": "*"}
        )
        self.assertEqual(response.status_code, 404)

    def test_a_star_matches_the_existing_representation(self) -> None:
        response = self.client.get(self.path, headers={"If-None-Match": "*"})
        self.assertEqual(response.status_code, 304)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
