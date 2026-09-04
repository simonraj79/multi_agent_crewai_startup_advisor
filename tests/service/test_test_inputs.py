"""The saved test inputs the docked panel runs from - 13 D3, criterion 7.

Three routes over `builder_test_inputs`, and the four things they have to get
right:

* **The three routes work at all.** The table shipped with plan 15 and its one
  read query with plan 10, which left the panel able to POINT at a saved input
  (`test_input_id`) and with no way to make one. Every row in this table was
  written by a test's own `insert()` until now.
* **Owner scoping, on the DOCUMENT and on the ROW.** Somebody else's document
  is a 404 before the rows underneath it are queried; somebody else's row is a
  404 from the row query itself.
* **404, never 403.** A 403 confirms the thing exists, which is the oracle
  `require_own_run` and `BuilderDocumentStore` both refuse to be.
* **`from_run_id` copies `out__*` off a finished run's own state**, which is
  D3's *"use last run's outputs as mocks"* - the cheapest way to get realistic
  mocks for a single-node test is a real run, once.

The last one is the reason this file builds on `AuthenticatedTwoUserCase` and
runs a real synthetic flow rather than seeding `flow_states` by hand: what it
has to prove is that the keys this route reads are the keys the RUNTIME writes,
and a hand-seeded row would prove only that the test and the route agree with
each other. Nothing here calls a model - every billable node is built by the
doubles `SYNTHETIC=1` installs - so the file costs nothing.
"""

from __future__ import annotations

import importlib.util
from typing import Any
import unittest

from brief_crew.config import MAX_TEST_INPUTS_PER_DOCUMENT
from tests.builder.test_compiler import input_node, output_node, scoper_node
from tests.builder.test_document import document, edge
from tests.service.identities import AuthenticatedTwoUserCase, wire

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
IDEA = "a scheduling assistant for clinics"


def two_step() -> Any:
    """idea -> a -> b -> report. Two billable steps, so two `out__*` slots."""

    return document(
        [
            input_node(),
            scoper_node("a"),
            scoper_node("b"),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "report"),
        ],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class TestInputRouteCase(AuthenticatedTwoUserCase):
    """One document owned by Alice, and the four calls every test here makes."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": wire(two_step())},
            headers=self.as_alice(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.document_id = created.json()["document"]["id"]

    def path(self, document_id: str | None = None) -> str:
        return f"/api/builder/workflows/{document_id or self.document_id}/test-inputs"

    def list_as(self, headers: dict[str, str] | None, document_id: str | None = None) -> Any:
        return self.client.get(self.path(document_id), headers=headers or {})

    def save_as(
        self,
        headers: dict[str, str] | None,
        document_id: str | None = None,
        **body: Any,
    ) -> Any:
        payload: dict[str, Any] = {"label": "clinic scheduling", "inputs": {"idea": IDEA}}
        payload.update(body)
        return self.client.post(self.path(document_id), json=payload, headers=headers or {})

    def delete_as(
        self, headers: dict[str, str] | None, test_input_id: str, document_id: str | None = None
    ) -> Any:
        return self.client.delete(
            f"{self.path(document_id)}/{test_input_id}", headers=headers or {}
        )


class TheThreeRoutes(TestInputRouteCase):
    def test_a_new_document_has_no_saved_inputs(self) -> None:
        response = self.list_as(self.as_alice())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_a_saved_input_comes_back_with_its_id_and_both_json_columns(self) -> None:
        response = self.save_as(self.as_alice())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["id"].startswith("ti_"))
        self.assertEqual(body["document_id"], self.document_id)
        self.assertEqual(body["label"], "clinic scheduling")
        self.assertEqual(body["inputs"], {"idea": IDEA})
        self.assertEqual(body["node_mocks"], {})

    def test_a_saved_input_is_then_listed(self) -> None:
        saved = self.save_as(self.as_alice()).json()
        rows = self.list_as(self.as_alice()).json()
        self.assertEqual([row["id"] for row in rows], [saved["id"]])

    def test_mocks_are_stored_and_returned_verbatim(self) -> None:
        mocks = {"a": "the scoped idea", "b": {"score": 7}}
        saved = self.save_as(self.as_alice(), node_mocks=mocks).json()
        self.assertEqual(saved["node_mocks"], mocks)
        self.assertEqual(self.list_as(self.as_alice()).json()[0]["node_mocks"], mocks)

    def test_delete_removes_the_row_and_answers_204(self) -> None:
        saved = self.save_as(self.as_alice()).json()
        response = self.delete_as(self.as_alice(), saved["id"])
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.list_as(self.as_alice()).json(), [])

    def test_deleting_the_same_row_twice_is_a_404(self) -> None:
        saved = self.save_as(self.as_alice()).json()
        self.assertEqual(self.delete_as(self.as_alice(), saved["id"]).status_code, 204)
        self.assertEqual(self.delete_as(self.as_alice(), saved["id"]).status_code, 404)

    def test_the_ceiling_is_a_422_naming_the_number(self) -> None:
        for index in range(MAX_TEST_INPUTS_PER_DOCUMENT):
            self.assertEqual(
                self.save_as(self.as_alice(), label=f"input {index}").status_code, 201
            )
        response = self.save_as(self.as_alice(), label="one too many")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn(str(MAX_TEST_INPUTS_PER_DOCUMENT), response.json()["detail"])

    def test_an_empty_label_is_refused_before_the_insert(self) -> None:
        self.assertEqual(self.save_as(self.as_alice(), label="").status_code, 422)

    def test_an_over_long_label_is_refused_rather_than_truncated(self) -> None:
        """The column is String(80); a dialect that truncates must not decide."""

        self.assertEqual(self.save_as(self.as_alice(), label="x" * 81).status_code, 422)


class OwnerScoping(TestInputRouteCase):
    """Rubric 14's half of this table: one author's rows are another's 404."""

    def test_somebody_elses_document_is_a_404_not_a_403(self) -> None:
        response = self.list_as(self.as_bob())
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("403", response.text)

    def test_saving_against_somebody_elses_document_is_a_404(self) -> None:
        self.assertEqual(self.save_as(self.as_bob()).status_code, 404)

    def test_a_document_that_does_not_exist_answers_the_same_404(self) -> None:
        """The whole point of the conflation: the two are indistinguishable."""

        theirs = self.list_as(self.as_bob()).json()["detail"]
        absent = self.list_as(self.as_alice(), document_id="ug_deadbeef").json()["detail"]
        self.assertEqual(theirs, absent)

    def test_bobs_row_is_invisible_in_alices_list(self) -> None:
        """Two owners, one document - which only an unowned document allows.

        Written against the ROW query rather than the document query, because
        the document check would otherwise be the only thing under test here
        and the row scoping would be vacuous.
        """

        from brief_crew.builder.store import BuilderTestInputStore

        store = BuilderTestInputStore(self.registry.persistence)
        store.create(
            self.document_id,
            user_id="user_bob",
            label="bob's own",
            inputs={"idea": "something else"},
        )
        mine = store.create(
            self.document_id,
            user_id="user_alice",
            label="alice's own",
            inputs={"idea": IDEA},
        )
        rows = self.list_as(self.as_alice()).json()
        self.assertEqual([row["id"] for row in rows], [mine.id])

    def test_deleting_somebody_elses_row_through_your_own_document_is_a_404(self) -> None:
        from brief_crew.builder.store import BuilderTestInputStore

        store = BuilderTestInputStore(self.registry.persistence)
        theirs = store.create(
            self.document_id,
            user_id="user_bob",
            label="bob's own",
            inputs={"idea": "something else"},
        )
        self.assertEqual(self.delete_as(self.as_alice(), theirs.id).status_code, 404)
        self.assertEqual(
            len(store.list(self.document_id, user_id="user_bob")),
            1,
            "the row must still be there",
        )

    def test_an_anonymous_caller_is_refused_by_the_auth_layer(self) -> None:
        """This app requires auth, so no row can be written with no owner."""

        self.assertEqual(self.list_as(None).status_code, 401)


class MocksFromARun(TestInputRouteCase):
    """D3: the cheapest way to get realistic mocks is a real run, once."""

    def completed_run(self) -> str:
        document_id, workflow_id = self.publish(two_step(), self.as_alice())
        self.document_id = document_id
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        return run_id

    def test_from_run_id_copies_every_out_slot_keyed_by_the_authors_node_id(self) -> None:
        """EVERY node that produced an output, not only the billable ones.

        Measured rather than assumed: the run writes `out__idea` and
        `out__report` too, because the input node seeds a value and the output
        node renders one. That is the right set to hand a single-node test - a
        node whose upstream is the input node needs `idea` mocked exactly as
        much as one whose upstream is an agent - and asserting the two agents
        alone would have been asserting a guess.
        """

        run_id = self.completed_run()
        saved = self.save_as(self.as_alice(), from_run_id=run_id)
        self.assertEqual(saved.status_code, 201, saved.text)
        mocks = saved.json()["node_mocks"]
        self.assertEqual(sorted(mocks), ["a", "b", "idea", "report"])
        self.assertTrue(all(str(value).strip() for value in mocks.values()))

    def test_the_prefix_is_stripped_so_the_keys_are_the_canvas_ids(self) -> None:
        """`out__a` in `flow_states` reaches the panel as `a`.

        The mock is replayed into the node the author drew, and the compiled
        state key is the runtime's business - the same separation
        `builder_graph_descriptor` makes about node ids.
        """

        run_id = self.completed_run()
        mocks = self.save_as(self.as_alice(), from_run_id=run_id).json()["node_mocks"]
        self.assertFalse([key for key in mocks if key.startswith("out__")])

    def test_an_explicit_mock_wins_over_the_copied_one(self) -> None:
        run_id = self.completed_run()
        saved = self.save_as(
            self.as_alice(), from_run_id=run_id, node_mocks={"a": "what I meant"}
        ).json()
        self.assertEqual(saved["node_mocks"]["a"], "what I meant")
        self.assertIn("b", saved["node_mocks"], "the other node still came from the run")

    def test_somebody_elses_run_is_a_404(self) -> None:
        run_id = self.completed_run()
        response = self.client.post(
            self.path(), json={"label": "theirs", "from_run_id": run_id}, headers=self.as_bob()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_a_run_that_does_not_exist_is_a_404(self) -> None:
        response = self.save_as(self.as_alice(), from_run_id="run-nope")
        self.assertEqual(response.status_code, 404, response.text)

    def test_the_saved_row_then_drives_a_node_test(self) -> None:
        """The loop closes: this route WRITES what plan 10's `load` reads.

        `mode: node_test` resolved a `test_input_id` from the moment plan 10
        landed and nothing could create one, so the positive path had never run
        end to end - only the three refusals. This is that path.
        """

        run_id = self.completed_run()
        workflow_id = self.document_id
        saved = self.save_as(self.as_alice(), from_run_id=run_id).json()
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={
                "workflow_id": workflow_id,
                "inputs": {"idea": IDEA},
                "mode": "node_test",
                "node_id": "b",
                "test_input_id": saved["id"],
            },
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        node_run = response.json()["run_id"]
        self.registry.wait(node_run, timeout=20)
        status = self.client.get(
            f"/api/runs/{node_run}", headers=self.as_alice()
        ).json()
        self.assertEqual(status["status"], "completed", status)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
