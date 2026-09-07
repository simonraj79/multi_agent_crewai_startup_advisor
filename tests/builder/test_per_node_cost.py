"""04 criterion 6, the server half: the validate ROUTE serves `per_node`.

`estimate_budget` has carried a per-node breakdown since plan 09 landed C5, and
`tests/builder/test_budget.py::PerNodeCostTests` proves the arithmetic. What
neither of those asks is the question the inspector's cost line actually
depends on: **does the key survive the response model, keyed on the author's own
canvas node id, on the one route the canvas calls every 400 ms?**

It is a separate question because `BuilderBudgetModel` is `extra="forbid"` and
built field by field in `BuilderBudgetModel.of`. A breakdown that exists on the
dataclass and is dropped, renamed or re-keyed on the way out looks exactly like
plan 04's recorded "today's state" - the line renders nothing and no test is red
- which is the state this file exists to make impossible to return to.

Nothing here calls a model. `POST /api/builder/validate` parses, bounds and
prices a document and runs none of it, so this whole module costs $0.00.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from brief_crew.builder import estimate_budget
from brief_crew.builder.document import BuilderDocument
from brief_crew.config import MODEL_BY_ID
from tests.builder.test_budget import AUTHORED_MODEL, one_authored_agent

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False


CHEAPER_MODEL = "qwen/qwen3.7-flash"

#: `model_id` is the spelling the price table is keyed on, which carries the
#: platform prefix `budget.py` adds before it looks a model up. The DOCUMENT
#: carries the bare registry id, so the two are deliberately different strings
#: for one model - asserted here rather than smoothed over, because a reader who
#: expects them to match will otherwise conclude the wrong node was priced.
PRICED_PREFIX = "openrouter/"


def _payload(document: BuilderDocument) -> dict[str, Any]:
    return {"document": json.loads(document.model_dump_json())}


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class PerNodeCostRouteTests(unittest.TestCase):
    """C5's `per_node` over the wire, on the route the inspector reads."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def _budget(self, document: BuilderDocument) -> dict[str, Any]:
        response = self.client.post("/api/builder/validate", json=_payload(document))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("budget", body)
        return body["budget"]

    def test_the_breakdown_is_keyed_on_the_authors_own_node_id(self) -> None:
        budget = self._budget(one_authored_agent())
        self.assertIn("per_node", budget)
        # `draft` is the id the author typed, not a compiled `n2_draft`. The
        # inspector looks the node up by the id on the card in front of it, so
        # a compiled spelling here would render nothing and say nothing.
        self.assertEqual(sorted(budget["per_node"]), ["draft"])

    def test_each_entry_carries_calls_dollars_and_the_model_it_was_priced_at(
        self,
    ) -> None:
        entry = self._budget(one_authored_agent())["per_node"]["draft"]
        self.assertEqual(sorted(entry), ["calls", "model_id", "usd"])
        self.assertGreater(entry["calls"], 0)
        self.assertGreater(entry["usd"], 0.0)
        self.assertEqual(entry["model_id"], PRICED_PREFIX + AUTHORED_MODEL)

    def test_the_served_figures_are_the_estimators_own(self) -> None:
        """R6: the client renders this number and never derives it.

        So the number on the wire has to BE the enforced estimate rather than a
        second arithmetic that happens to agree today - which is how a meter and
        a refusal come to disagree.
        """
        document = one_authored_agent()
        served = self._budget(document)["per_node"]["draft"]
        computed = estimate_budget(document).per_node["draft"]
        self.assertEqual(served["calls"], computed.calls)
        self.assertAlmostEqual(served["usd"], computed.usd, places=10)
        self.assertEqual(served["model_id"], computed.model)

    def test_the_per_node_dollars_still_sum_to_the_total_over_the_wire(self) -> None:
        budget = self._budget(one_authored_agent())
        self.assertAlmostEqual(
            sum(entry["usd"] for entry in budget["per_node"].values()),
            budget["static_cost_usd"],
            places=6,
        )

    def test_changing_the_model_changes_the_line(self) -> None:
        """The criterion's own event: a model change reprices THIS node.

        Asserted on the route rather than on the estimator, because what the
        author sees move is the response - and both figures below are served by
        the same handler off the same document but for the model word. The call
        count is asserted UNCHANGED beside it, so the dollars moving is the
        price moving rather than the shape of the graph moving underneath it.
        """
        dear = self._budget(one_authored_agent())["per_node"]["draft"]
        cheap = self._budget(
            one_authored_agent(llm={"model": CHEAPER_MODEL}, tier="cheap")
        )["per_node"]["draft"]

        self.assertEqual(cheap["model_id"], PRICED_PREFIX + CHEAPER_MODEL)
        self.assertEqual(cheap["calls"], dear["calls"])
        self.assertLess(cheap["usd"], dear["usd"])

    def test_a_wide_endpoint_spread_costs_MORE_than_a_dearer_headline(self) -> None:
        """Measured, and it is the one direction a reader will not predict.

        AMENDED BY AUDIT M14, which invalidated this test's premise rather than
        its point. It read `test_a_nitro_variant_costs_MORE_than_the_dearer_
        headline` and swapped the escalation model for the cheaper flash-lite
        `:nitro` preset, because only a `:nitro` spelling was inflated - $0.157
        became $0.182. Every slug is inflated by its own measured endpoint
        spread now, so the escalation preset carries the same 1.8x and the
        comparison no longer inverts: $0.283 against $0.182.

        The POINT survives, and one roster pair still makes it plainly.
        `openai/gpt-oss-120b` publishes cheaper than `openai/gpt-4.1-nano` on
        BOTH halves - $0.037/$0.17 against $0.10/$0.40 - and its floor here is
        $0.0072 against $0.0171. Priced at each model's dearest endpoint
        (9.4595x against 1.1x) it costs nearly four times as much: $0.0679
        against $0.0188. So the cost line is reporting the number the ceiling
        is enforced against and not a headline price, which is the whole reason
        04 D6 asks the SERVER for it instead of computing it beside the picker
        from a published rate.
        """
        cheap_headline = self._budget(
            one_authored_agent(llm={"model": "openai/gpt-oss-120b"}, tier="cheap")
        )["per_node"]["draft"]
        dear_headline = self._budget(
            one_authored_agent(llm={"model": "openai/gpt-4.1-nano"}, tier="cheap")
        )["per_node"]["draft"]

        wide = MODEL_BY_ID["openai/gpt-oss-120b"]
        narrow = MODEL_BY_ID["openai/gpt-4.1-nano"]
        self.assertLess(wide.cost_in, narrow.cost_in)
        self.assertLess(wide.cost_out, narrow.cost_out)

        self.assertEqual(cheap_headline["calls"], dear_headline["calls"])
        self.assertGreater(cheap_headline["usd"], dear_headline["usd"])

    def test_a_library_agent_is_priced_too_so_the_line_is_not_authored_only(
        self,
    ) -> None:
        """Every BILLABLE node appears, which is what makes the line general."""
        from tests.builder.test_document import validator_shaped_document

        budget = self._budget(validator_shaped_document())
        self.assertTrue(budget["per_node"], "a billable graph priced nothing")
        for entry in budget["per_node"].values():
            self.assertGreaterEqual(entry["calls"], 1)


if __name__ == "__main__":
    unittest.main()
