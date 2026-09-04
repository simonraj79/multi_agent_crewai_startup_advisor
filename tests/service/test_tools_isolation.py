"""One author's custom tool is invisible to another - plan 06 criterion 7.

The claim is not "the list is filtered". It is that a DOCUMENT naming somebody
else's tool validates with `tool-unknown` while the owner's validates clean, and
those are two different assertions: a filtered list with an unfiltered validator
would pass the first and fail an author at publish, and a validator that refused
every `ut_` id would pass the second by refusing everybody.

Both directions, in one test each, over the same document with only the
credentials of the caller changed. Rubric 14.

No cost: a synthetic app over in-memory SQLite. No network, no model.
"""

from __future__ import annotations

import unittest
from typing import Any

from brief_crew.builder.tools import TOOL_CREDENTIAL_REQUIRED, TOOL_PARAM_INVALID, TOOL_UNKNOWN
from tests.builder.test_document import agent_node, chain, document, input_node, node, output_node
from tests.service.identities import AuthenticatedTwoUserCase, wire

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

CUSTOM = "/api/builder/tools/custom"
VALIDATE = "/api/builder/validate"

WEATHER = {
    "name": "weather_lookup",
    "description": "Current weather for a city.",
    "properties": [
        {"name": "city", "type": "string", "description": "City", "required": True}
    ],
    "request": {
        "method": "GET",
        "url": "https://api.example.test/weather?q={city}",
        "timeout_seconds": 10,
        "max_response_bytes": 4096,
    },
}


def graph_with_tool(tool_id: str, **config: Any):
    """One agent, one attached tool, wired the shortest legal way.

    `attach` and `member` are structural, so the tool sits BESIDE the flow: the
    chain is input -> writer -> report, and the tool reaches the agent on its
    `attach` port. A tool in the flow chain would be a different defect and a
    different code.
    """

    return document(
        [
            input_node(),
            agent_node("writer"),
            node("hands", "tool", {"tool_id": tool_id, **config}),
            output_node(),
        ],
        [
            *chain("idea", "writer", "report"),
            {
                "id": "a1",
                "source": "hands",
                "source_port": "out",
                "target": "writer",
                "target_port": "attach",
            },
        ],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class CustomToolIsolationTests(AuthenticatedTwoUserCase):
    def _codes(self, headers: dict[str, str], doc: Any) -> list[str]:
        response = self.client.post(
            VALIDATE, json={"document": wire(doc)}, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [problem["code"] for problem in response.json()["problems"]]

    def test_the_owners_document_validates_clean_and_a_strangers_does_not(self) -> None:
        created = self.client.post(CUSTOM, json=WEATHER, headers=self.as_alice())
        self.assertEqual(created.status_code, 201, created.text)
        tool_id = created.json()["id"]
        doc = graph_with_tool(tool_id)

        self.assertNotIn(TOOL_UNKNOWN, self._codes(self.as_alice(), doc))
        self.assertIn(TOOL_UNKNOWN, self._codes(self.as_bob(), doc))

    def test_deleting_it_makes_the_owners_own_document_report_it_too(self) -> None:
        """The same code, and deliberately so.

        A deleted tool and a stranger's tool are one answer for the reason
        `credential-missing` gives: a canvas that told them apart would be an
        oracle for other people's ids, and the repair is the same either way -
        pick a tool you have.
        """

        created = self.client.post(CUSTOM, json=WEATHER, headers=self.as_alice())
        tool_id = created.json()["id"]
        doc = graph_with_tool(tool_id)
        self.assertNotIn(TOOL_UNKNOWN, self._codes(self.as_alice(), doc))

        self.assertEqual(
            self.client.delete(f"{CUSTOM}/{tool_id}", headers=self.as_alice()).status_code,
            204,
        )
        self.assertIn(TOOL_UNKNOWN, self._codes(self.as_alice(), doc))

    def test_a_builtin_id_is_checked_for_everybody_and_a_made_up_one_is_refused(self) -> None:
        self.assertIn(
            TOOL_UNKNOWN, self._codes(self.as_alice(), graph_with_tool("no_such_tool"))
        )
        self.assertNotIn(
            TOOL_UNKNOWN,
            self._codes(self.as_alice(), graph_with_tool("scrape_website")),
        )

    def test_a_param_outside_the_entrys_schema_is_reported_not_ignored(self) -> None:
        """The gauntlet's "forbidden: a parameter the compiler ignores", in reverse."""

        codes = self._codes(
            self.as_alice(),
            graph_with_tool("web_search", params={"provider": "nope"}),
        )
        self.assertIn(TOOL_PARAM_INVALID, codes)

    def test_an_entry_needing_a_key_with_none_named_is_its_own_code(self) -> None:
        """A DIFFERENT repair from `credential-missing`, and so a different code.

        `credential-missing` means "that id is not yours"; this means "add a key
        of this kind and pick it". Plan 06 D4 reuses the first name for both;
        `compiler.py` already states the rule that a different repair earns a
        different code, and this follows it. Recorded as a departure in the
        plan's Status.
        """

        codes = self._codes(self.as_alice(), graph_with_tool("firecrawl_search"))
        self.assertIn(TOOL_CREDENTIAL_REQUIRED, codes)

    def test_an_optional_key_is_not_demanded(self) -> None:
        """`assess_technical_feasibility` runs unauthenticated at a lower rate
        limit, so a missing GitHub token is a fact about throughput and not a
        problem with the graph."""

        codes = self._codes(
            self.as_alice(), graph_with_tool("assess_technical_feasibility")
        )
        self.assertNotIn(TOOL_CREDENTIAL_REQUIRED, codes)


if __name__ == "__main__":
    unittest.main()
