"""WHOSE control keys `create_run` refuses, and the comment that said otherwise.

The check reads as if it fails closed to the union of every workflow's reserved
keys. It does not, and never did: ``reserved_run_input_keys`` answers a DECLARED
workflow its own set, so ``POST`` with ``inputs.verdict`` against ``brief-flow``
is a 202 while the comment beside the line promised a 422. Two layers had been
narrowed for the same good reason - a third workflow whose own declared prompt
is ``brief`` was being told, by a workflow that has never heard of it, that its
prompt was Brief Crew's reserved result slot - and only one of them said so.

The narrowing is kept and this module is what keeps it honest. ``route``,
``brief`` and ``usage`` are Brief Crew's state names and ordinary English words
on anybody else's graph; a key belonging to a flow that is not the one running
reaches nothing. What must not move is the half that protects something, so
every case below is one of the three:

* a workflow's OWN control keys are refused (:class:`ItsOwnKeysAreStillRefused`);
* another workflow's are NOT, deliberately (:class:`AnotherWorkflowsKeysArePermitted`);
* a workflow registered without declaring its state names falls back to the
  UNION (:class:`AnUndeclaredWorkflowStillFailsClosed`), which is the fail-closed
  half, and the reason this asks ``reserved_run_input_keys`` rather than reading
  one map entry itself.

``tests/service/test_gates_mode.py`` pins the two smuggling attempts that must
never be reachable for any id, declared or invented; nothing here weakens them.

No cost. The built-in cases run against ``synthetic=True``, whose runners are
deterministic doubles, and the third-workflow cases reuse
``test_unknown_workflow``'s ``InertRunner``.
"""

from __future__ import annotations

import importlib.util
import unittest


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:  # pragma: no branch - the import is the skip condition
    from tests.service.test_unknown_workflow import (
        THIRD_ID,
        THIRD_INPUT_FIELD,
        ThirdWorkflowTestCase,
    )
else:  # pragma: no cover - mirrors the skip in every other service module
    ThirdWorkflowTestCase = unittest.TestCase  # type: ignore[assignment,misc]
    THIRD_ID = "third-workflow"
    THIRD_INPUT_FIELD = "brief"


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ItsOwnKeysAreStillRefused(ThirdWorkflowTestCase):
    """The half that protects something, and it is untouched."""

    def test_brief_flow_may_not_carry_its_own_state_key(self) -> None:
        """`route` is `BriefState`'s cache router slot. On a Brief Crew run it
        is a control key, and CrewAI merges `inputs` into state wholesale.

        Answered by the request SCHEMA rather than by `create_run`, because
        `brief-flow` is DECLARED - both layers then read the same map entry and
        the schema gets there first, which is why the assertion is on the whole
        body and not on a `detail` string.
        """

        client = self.builtin_client()

        response = client.post(
            "/api/sessions/s-own/runs",
            json={
                "workflow_id": "brief-flow",
                "inputs": {"topic": "kettles", "route": "cache_hit"},
            },
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("route", response.text)

    def test_the_three_crewai_keys_are_refused_for_every_id(self) -> None:
        """These are the globals, and they are refused one layer earlier - by
        the request SCHEMA, which needs no registry to know them."""

        client = self.builtin_client()

        for key in ("id", "no_gates", "sequential_branches"):
            with self.subTest(key=key):
                response = client.post(
                    "/api/sessions/s-global/runs",
                    json={
                        "workflow_id": "brief-flow",
                        "inputs": {"topic": "kettles", key: True},
                    },
                )
                self.assertEqual(response.status_code, 422, response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AnotherWorkflowsKeysArePermitted(ThirdWorkflowTestCase):
    """The decision, pinned so it is a decision and not a drift.

    A future reader who makes the code match the old comment - swapping in
    `all_reserved_run_input_keys()` - fails here, and the failure names the
    trade rather than leaving them to rediscover it.
    """

    def test_brief_flow_accepts_the_validators_control_key(self) -> None:
        client = self.builtin_client()

        response = client.post(
            "/api/sessions/s-cross/runs",
            json={
                "workflow_id": "brief-flow",
                "inputs": {"topic": "kettles", "verdict": "REJECT"},
            },
        )

        self.assertEqual(response.status_code, 202, response.text)

    def test_a_third_workflows_prompt_is_not_brief_crews_result_slot(self) -> None:
        """The collision the subtraction exists for, from the other side.

        `THIRD_INPUT_FIELD` is `brief`, which is a reserved key on `brief-flow`.
        Refusing it here would tell an author their own declared prompt belongs
        to a workflow they have never heard of.
        """

        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self.launch(
            client,
            {"workflow_id": THIRD_ID, "inputs": {THIRD_INPUT_FIELD: "a real brief"}},
        )

        self.assertEqual(response.status_code, 202, response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AnUndeclaredWorkflowStillFailsClosed(ThirdWorkflowTestCase):
    """The fallback, which is the whole reason the union is still asked for.

    `register_third` puts a workflow in the maps the handler consults and never
    calls `register_workflow_reserved_run_input_keys`, which is exactly the
    registration defect `reserved_run_input_keys` fails closed for: "this
    workflow's own keys" would otherwise answer the empty set.
    """

    def test_an_undeclared_workflow_is_refused_the_whole_union(self) -> None:
        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)

        response = self.launch(
            client,
            {
                "workflow_id": THIRD_ID,
                "inputs": {THIRD_INPUT_FIELD: "a real brief", "verdict": "REJECT"},
            },
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("verdict", response.json()["detail"])

    def test_but_not_its_own_prompt(self) -> None:
        """The subtraction, at the one layer that can make it: `brief` is in
        the union it just fell back to, and it is this workflow's prompt."""

        from brief_crew.config import all_reserved_run_input_keys

        self.assertIn(THIRD_INPUT_FIELD, all_reserved_run_input_keys())

        client = self.register_third(gated=False, input_field=THIRD_INPUT_FIELD)
        response = self.launch(
            client,
            {"workflow_id": THIRD_ID, "inputs": {THIRD_INPUT_FIELD: "a real brief"}},
        )

        self.assertEqual(response.status_code, 202, response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
