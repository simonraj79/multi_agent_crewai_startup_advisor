"""The per-gate revise bound, and why it cannot live anywhere cheaper.

A ``decision: "revise"`` at either gate re-runs an ESCALATION_MODEL crew - the
Scoper at ``confirm_scope``, the Synthesist at ``review_verdict`` - on an
endpoint that is unauthenticated by design and that deliberately exempts gate
replies from admission control so a flood can never strand a human mid-run.
``route_scope -> revise_scope -> confirm_scope`` is a real cycle in the flow
graph, so nothing about a revise loop terminates on its own. Before this bound
the only thing between one run and unbounded escalation-tier spend was the
operator getting bored.

The tests are organised around the one fact that decides the whole design:
**every shipped gate reply builds a brand new flow object.** ``answer_gate`` ->
``ValidatorFlow.from_pending()`` -> ``resume()``, once per reply. So a bound
held in memory is not a bound at all, and the tests that matter most here are
the ones that go through that path rather than through an in-process kickoff.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crewai.flow.async_feedback import HumanFeedbackPending

from brief_crew import config as project_config
from brief_crew.config import (
    GATE_REVISE_TURNS_METADATA_KEY,
    VALIDATOR_MAX_GATE_TURNS,
    VALIDATOR_MAX_METHOD_CALLS,
)
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.validator_flow import (
    GATE_NODES,
    GATE_TURN_FIELDS,
    ValidatorCrewFactories,
    ValidatorFeedbackProvider,
    ValidatorFlow,
    ValidatorState,
    claim_revise_turn,
    revise_turns_used,
)
from tests.validator.test_flow import FakeRunner, fixtures


class ScriptedGates:
    """Answer each gate from a fixed script, recording what was asked.

    Stands in for ``ValidatorFeedbackProvider.request_feedback``, which is the
    seam an in-process caller uses: a scripted provider, a future auto mode, or
    a test. It bypasses the durable pause entirely, which is exactly why the
    in-process tests below cannot substitute for the resume tests.

    Patched onto the class as an *instance*, so it is not a descriptor and
    ``provider.request_feedback`` hands back this object unbound: the signature
    below is therefore ``(context, flow)`` with no leading provider argument,
    unlike a plain function patched into the same slot.
    """

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.asked: list[str] = []

    def __call__(self, context: object, _flow: object) -> str:
        self.asked.append(context.method_name)
        # A script that runs dry means the flow asked more times than the test
        # predicted, which is the failure this feature is about. Say so here
        # rather than letting IndexError surface from inside CrewAI.
        if not self.replies:
            raise AssertionError(
                f"the flow asked {context.method_name} more times than the "
                f"script had replies; asked so far: {self.asked}"
            )
        return self.replies.pop(0)


def _factories() -> tuple[ValidatorCrewFactories, dict[str, FakeRunner]]:
    scope, market, sentiment, feasibility, verdict, report = fixtures()
    runners = {
        "scope": FakeRunner(scope),
        "market": FakeRunner(market),
        "sentiment": FakeRunner(sentiment),
        "feasibility": FakeRunner(feasibility),
        "synthesis": FakeRunner(verdict),
        "report": FakeRunner(report),
    }
    factories = ValidatorCrewFactories(
        scope=lambda: runners["scope"],
        market=lambda: runners["market"],
        sentiment=lambda: runners["sentiment"],
        feasibility=lambda: runners["feasibility"],
        synthesis=lambda *_: runners["synthesis"],
        report=lambda *_: runners["report"],
    )
    return factories, runners


REVISE = '{"decision": "revise", "feedback": "narrow it"}'
APPROVE = '{"decision": "approve"}'


class GateTurnConfigTests(unittest.TestCase):
    """The knob, its default, and the derived backstop that depends on it."""

    def test_the_default_is_five_turns_per_gate(self) -> None:
        self.assertEqual(VALIDATOR_MAX_GATE_TURNS, 5)

    def test_zero_is_a_legal_setting(self) -> None:
        # `minimum=0`, unlike most knobs in config.py, because "approve or
        # cancel, no revising" is a coherent deployment stance and the gate
        # payload degrades correctly for it (the Revise option is not offered).
        with patch.dict(os.environ, {"VALIDATOR_MAX_GATE_TURNS": "0"}):
            self.assertEqual(
                project_config._env_positive_int(
                    "VALIDATOR_MAX_GATE_TURNS", 5, minimum=0
                ),
                0,
            )

    def test_a_negative_setting_is_refused_at_import(self) -> None:
        with patch.dict(os.environ, {"VALIDATOR_MAX_GATE_TURNS": "-1"}):
            with self.assertRaises(ValueError):
                project_config._env_positive_int(
                    "VALIDATOR_MAX_GATE_TURNS", 5, minimum=0
                )

    def test_the_backstop_clears_the_bound_it_backs_up(self) -> None:
        """The two constants are coupled, so pin the coupling.

        The measured ceiling is `VALIDATOR_MAX_GATE_TURNS + 1` calls of the
        gate method in one flow object (see
        ``MaxMethodCallsTests.test_the_measured_ceiling_is_turns_plus_one``).
        A backstop set below that would clip a legitimate in-process run with a
        RecursionError instead of the graceful approval the cap is supposed to
        produce - so raising VALIDATOR_MAX_GATE_TURNS without raising this must
        fail here rather than in a paid run.
        """
        self.assertEqual(VALIDATOR_MAX_METHOD_CALLS, VALIDATOR_MAX_GATE_TURNS + 2)
        self.assertGreater(VALIDATOR_MAX_METHOD_CALLS, VALIDATOR_MAX_GATE_TURNS + 1)


class GateTurnStateTests(unittest.TestCase):
    """The counters are ordinary declared state, and that is the whole trick."""

    def test_a_fresh_state_has_spent_nothing(self) -> None:
        # Turn accounting counts revises ALREADY HONOURED, so a gate that has
        # never been answered reads 0 and the operator has the full budget.
        # "The first ask is turn 0" - the Nth revise is honoured, the (N+1)th
        # is not.
        state = ValidatorState()
        self.assertEqual(revise_turns_used(state, "scope"), 0)
        self.assertEqual(revise_turns_used(state, "verdict"), 0)
        self.assertFalse(state.scope_revise_capped)
        self.assertFalse(state.verdict_revise_capped)

    def test_claiming_spends_exactly_the_cap_then_refuses(self) -> None:
        state = ValidatorState()
        with patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 3):
            granted = [claim_revise_turn(state, "scope") for _ in range(5)]
        self.assertEqual(granted, [True, True, True, False, False])
        self.assertEqual(state.scope_revise_turns, 3)
        self.assertTrue(state.scope_revise_capped)

    def test_a_zero_cap_refuses_the_very_first_revise(self) -> None:
        state = ValidatorState()
        with patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 0):
            self.assertFalse(claim_revise_turn(state, "scope"))
        self.assertEqual(state.scope_revise_turns, 0)
        self.assertTrue(state.scope_revise_capped)

    def test_the_two_gates_hold_separate_budgets(self) -> None:
        # They are separate conversations about separate artefacts and they
        # re-run different crews, so spending the scope budget must not
        # silently disarm the operator at the verdict.
        state = ValidatorState()
        with patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 1):
            self.assertTrue(claim_revise_turn(state, "scope"))
            self.assertFalse(claim_revise_turn(state, "scope"))
            self.assertTrue(claim_revise_turn(state, "verdict"))
        self.assertEqual(state.scope_revise_turns, 1)
        self.assertEqual(state.verdict_revise_turns, 1)

    def test_every_gate_node_maps_to_a_counter(self) -> None:
        # `GATE_NODES` is what the feedback provider looks the gate up in and
        # `GATE_TURN_FIELDS` is what the router spends; a third gate added to
        # one and not the other would silently be unbounded.
        self.assertEqual(set(GATE_NODES.values()), set(GATE_TURN_FIELDS))
        declared = set(ValidatorState.model_fields)
        for used_field, capped_field in GATE_TURN_FIELDS.values():
            self.assertIn(used_field, declared)
            self.assertIn(capped_field, declared)


class MaxMethodCallsTests(unittest.TestCase):
    """CrewAI's own loop guard: what it can do here, and what it cannot."""

    def setUp(self) -> None:
        patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[]).start()
        self.addCleanup(patch.stopall)

    def test_the_subclass_field_default_is_what_the_runtime_uses(self) -> None:
        """`max_method_calls` CAN be set from a Flow subclass, and this is how.

        It is a plain pydantic Field on ``Flow``
        (crewai/flow/runtime/__init__.py:614), so redeclaring it on the
        subclass changes the value the enforcement at :3333 reads. Asserted
        against CrewAI's shipped default as well, so a test that passed because
        both happened to be 100 would be visible.
        """
        from crewai.flow import Flow

        self.assertEqual(Flow.model_fields["max_method_calls"].default, 100)
        self.assertEqual(ValidatorFlow().max_method_calls, VALIDATOR_MAX_METHOD_CALLS)
        self.assertNotEqual(ValidatorFlow().max_method_calls, 100)

    def test_the_declarative_config_mirrors_the_field_and_not_the_reverse(
        self,
    ) -> None:
        """Which of the two ``max_method_calls`` is the one that binds.

        ``FlowDefinition.config.max_method_calls``
        (crewai/flow/flow_definition.py:219) reads like the declared knob, but
        it is downstream, not upstream: ``_build_config_definition``
        (crewai/flow/dsl/_utils.py:221-238) copies CLASS FIELD defaults into
        the definition, and the enforcement at
        crewai/flow/runtime/__init__.py:3333 reads ``self.max_method_calls``,
        the instance field. So the subclass field is the single source and the
        definition merely reflects it.

        Both halves are asserted, because getting the direction backwards is
        the plausible mistake: writing the definition's config would have been
        a no-op that read as a fix.
        """
        flow = ValidatorFlow()
        self.assertEqual(
            flow._definition.config.max_method_calls, VALIDATOR_MAX_METHOD_CALLS
        )

        # The constructor kwarg moves the instance field - the one the
        # enforcement reads - while the definition keeps reporting the class
        # default. Nothing here writes to ``_definition``: it is built once per
        # class and shared by every instance, so a test that mutated it would
        # quietly rewrite the value for the rest of the session.
        overridden = ValidatorFlow(max_method_calls=3)
        self.assertEqual(overridden.max_method_calls, 3)
        self.assertEqual(
            overridden._definition.config.max_method_calls, VALIDATOR_MAX_METHOD_CALLS
        )

    def test_the_measured_ceiling_is_turns_plus_one(self) -> None:
        """Pin the measurement `VALIDATOR_MAX_METHOD_CALLS` is derived from.

        ``_method_call_counts`` is keyed by METHOD NAME, so the binding number
        is the most-called single method in one flow object. With T revises at
        each gate that is the gate method itself: entered once to ask, then
        once more after each revise. Everything else is 1, or T for the revise
        methods. So T+1 is the ceiling and the backstop needs T+2.
        """
        turns = 3
        factories, _ = _factories()
        scope, *_ = fixtures()
        script = ScriptedGates(
            [REVISE] * turns + [APPROVE] + [REVISE] * turns + [APPROVE]
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH", Path(directory) / "v.md"
            ), patch(
                "brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", turns
            ), patch.object(
                ValidatorFeedbackProvider, "request_feedback", script
            ):
                flow = ValidatorFlow(crew_factories=factories)
                flow.kickoff(inputs={"idea": scope.startup_idea})

        counts = dict(flow._method_call_counts)
        self.assertEqual(counts["confirm_scope"], turns + 1)
        self.assertEqual(counts["route_scope"], turns + 1)
        self.assertEqual(counts["revise_scope"], turns)
        self.assertEqual(max(counts.values()), turns + 1)

    def test_the_backstop_is_in_force_and_not_decoration(self) -> None:
        """A cap below the ceiling really does raise, so the field is live.

        Without this the previous test would only prove that a number was
        stored on the model. Two revises need ``confirm_scope`` three times;
        ``max_method_calls=2`` therefore has to stop the run.
        """
        factories, _ = _factories()
        scope, *_ = fixtures()
        script = ScriptedGates([REVISE, REVISE, APPROVE, APPROVE])
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH", Path(directory) / "v.md"
            ), patch(
                "brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 5
            ), patch.object(
                ValidatorFeedbackProvider, "request_feedback", script
            ):
                flow = ValidatorFlow(crew_factories=factories, max_method_calls=2)
                with self.assertRaises(RecursionError) as caught:
                    flow.kickoff(inputs={"idea": scope.startup_idea})
        self.assertIn("confirm_scope", str(caught.exception))

    def test_the_backstop_resets_on_every_resume(self) -> None:
        """Why CrewAI's guard cannot BE the bound, stated as an assertion.

        ``_method_call_counts`` is a ``PrivateAttr``
        (crewai/flow/runtime/__init__.py:756): never serialized, never
        restored. ``from_pending()`` builds a fresh instance, so the counter it
        reads is empty no matter how many replies came before. That is the
        whole reason the durable bound lives on ``ValidatorState``.
        """
        self.assertIn("_method_call_counts", ValidatorFlow.__private_attributes__)
        flow = ValidatorFlow()
        flow._method_call_counts["confirm_scope"] = 99  # type: ignore[index]
        self.assertEqual(ValidatorFlow()._method_call_counts, {})


class InProcessGateTurnCapTests(unittest.TestCase):
    """The router's behaviour when the operator keeps pressing Revise."""

    def setUp(self) -> None:
        patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[]).start()
        self.addCleanup(patch.stopall)

    def _run(self, cap: int, replies: list[str]) -> tuple[ValidatorFlow, ScriptedGates, dict[str, FakeRunner]]:
        factories, runners = _factories()
        scope, *_ = fixtures()
        script = ScriptedGates(replies)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH", Path(directory) / "v.md"
            ), patch(
                "brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", cap
            ), patch.object(
                ValidatorFeedbackProvider, "request_feedback", script
            ):
                flow = ValidatorFlow(crew_factories=factories)
                flow.kickoff(inputs={"idea": scope.startup_idea})
        return flow, script, runners

    def test_the_nth_revise_is_honoured_and_the_n_plus_first_is_not(self) -> None:
        # Cap 2. Three revises are sent at the scope gate; the first two loop
        # back through revise_scope, the third is converted to an approval and
        # the run goes on. The asked list is the readable version of that: the
        # gate is entered three times, not four.
        flow, script, runners = self._run(
            cap=2, replies=[REVISE, REVISE, REVISE, APPROVE]
        )
        self.assertEqual(
            script.asked,
            ["confirm_scope", "confirm_scope", "confirm_scope", "review_verdict"],
        )
        self.assertEqual(flow.state.scope_revise_turns, 2)
        self.assertTrue(flow.state.scope_revise_capped)
        self.assertEqual(flow.state.scope_route, "scope_approved")
        # One initial scoping plus exactly two reruns: the third revise bought
        # no escalation-tier call, which is the entire point of the bound.
        self.assertEqual(len(runners["scope"].inputs), 3)

    def test_the_capped_reply_becomes_an_approval_rather_than_a_failure(self) -> None:
        # The alternatives were considered and rejected: failing the run would
        # discard the escalation-tier scope already paid for, and refusing the
        # reply would park the run at a gate with nothing left to do but
        # expire. Going forward keeps the money already spent and still bounds
        # the money not yet spent - so the run must actually FINISH.
        _, _, report = fixtures()[0], None, fixtures()[5]
        flow, _, _ = self._run(cap=1, replies=[REVISE, REVISE, APPROVE])
        self.assertEqual(flow.state.report, report)
        self.assertEqual(flow.state.scope_route, "scope_approved")

    def test_the_verdict_gate_is_bounded_the_same_way(self) -> None:
        flow, script, runners = self._run(
            cap=1, replies=[APPROVE, REVISE, REVISE]
        )
        self.assertEqual(
            script.asked, ["confirm_scope", "review_verdict", "review_verdict"]
        )
        self.assertEqual(flow.state.verdict_revise_turns, 1)
        self.assertTrue(flow.state.verdict_revise_capped)
        self.assertEqual(flow.state.verdict_route, "verdict_approved")
        # One synthesis plus one rerun. The Synthesist is the escalation-tier
        # agent that runs at reasoning_effort=high, so this is the most
        # expensive turn in the pipeline.
        self.assertEqual(len(runners["synthesis"].inputs), 2)

    def test_an_approve_never_spends_a_turn(self) -> None:
        # The counter must move only on the decision that costs money. A run
        # answered "approve" at both gates has spent nothing and, had it
        # revised later, would still have its whole budget.
        flow, _, _ = self._run(cap=2, replies=[APPROVE, APPROVE])
        self.assertEqual(flow.state.scope_revise_turns, 0)
        self.assertEqual(flow.state.verdict_revise_turns, 0)
        self.assertFalse(flow.state.scope_revise_capped)
        self.assertFalse(flow.state.verdict_revise_capped)

    def test_a_zero_cap_refuses_the_first_revise_and_still_completes(self) -> None:
        flow, script, runners = self._run(cap=0, replies=[REVISE, REVISE])
        self.assertEqual(script.asked, ["confirm_scope", "review_verdict"])
        self.assertEqual(flow.state.scope_revise_turns, 0)
        self.assertTrue(flow.state.scope_revise_capped)
        self.assertEqual(len(runners["scope"].inputs), 1)

    def test_an_unattended_run_is_untouched(self) -> None:
        """`no_gates` auto-approves, so it can never revise and never counts.

        Worth asserting rather than assuming: the unattended mode is the one
        the cost note in config.py calls out as having no human brake, so a
        bound that accidentally *fired* there - converting nothing, or leaving
        a `_capped` flag set - would be misreported spend on the one path that
        already worries people.
        """
        factories, runners = _factories()
        scope, *_rest = fixtures()
        report = fixtures()[5]
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH", Path(directory) / "v.md"
            ), patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 0):
                flow = ValidatorFlow(crew_factories=factories)
                result = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "no_gates": True}
                )
        self.assertEqual(result, report)
        self.assertEqual(flow.state.scope_revise_turns, 0)
        self.assertEqual(flow.state.verdict_revise_turns, 0)
        self.assertFalse(flow.state.scope_revise_capped)
        self.assertFalse(flow.state.verdict_revise_capped)
        self.assertEqual(len(runners["scope"].inputs), 1)


class SeedingTheCounterTests(unittest.TestCase):
    """The counters are state, and state is reachable from the run endpoint."""

    def test_the_state_field_really_is_settable_from_kickoff_inputs(self) -> None:
        """The hole this reservation closes, demonstrated rather than asserted.

        CrewAI merges kickoff inputs into the flow's pydantic state wholesale,
        so a counter declared on ``ValidatorState`` IS part of the public
        request body until something strips it. This test exists so the next
        person can see that the reservation below is load-bearing and not
        ceremony.
        """
        flow = ValidatorFlow()
        flow._initialize_state({"idea": "x", "scope_revise_turns": 4})
        self.assertEqual(flow.state.scope_revise_turns, 4)

    def test_all_four_counter_fields_are_reserved(self) -> None:
        from brief_crew.config import PUBLIC_RUN_INPUT_KEYS, RESERVED_RUN_INPUT_KEYS

        for used_field, capped_field in GATE_TURN_FIELDS.values():
            for name in (used_field, capped_field):
                with self.subTest(name=name):
                    self.assertIn(name, RESERVED_RUN_INPUT_KEYS)
                    self.assertNotIn(name, PUBLIC_RUN_INPUT_KEYS)

    def test_the_request_schema_refuses_a_seeded_counter(self) -> None:
        from brief_crew.service.models import CreateRunRequest

        for used_field, capped_field in GATE_TURN_FIELDS.values():
            for name in (used_field, capped_field):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError) as caught:
                        CreateRunRequest(
                            workflow_id="idea-validator",
                            inputs={"idea": "x", name: 0},
                        )
                    self.assertIn(name, str(caught.exception))

    def test_a_negative_seed_could_not_buy_extra_turns_anyway(self) -> None:
        # Belt and braces behind the reservation. `revise_turns_used` floors at
        # zero, so even a counter that somehow arrived negative cannot hand a
        # caller more escalation-tier calls than the cap allows.
        state = ValidatorState(scope_revise_turns=-1000)
        self.assertEqual(revise_turns_used(state, "scope"), 0)
        with patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", 1):
            self.assertTrue(claim_revise_turn(state, "scope"))
            self.assertFalse(claim_revise_turn(state, "scope"))


class DurableGateTurnTests(unittest.TestCase):
    """The bound across ``from_pending()`` / ``resume()`` - the only path that ships.

    Every in-process test above answers the gate on a live flow object. No
    operator ever does that: ``registry.answer_gate`` writes the durable answer
    and then calls ``ValidatorFlow.from_pending(...).resume(feedback)``, which
    constructs a NEW flow per reply. This class drives that loop by hand -
    kickoff, pause, reload from the store, resume, pause again - so the thing
    being asserted is the thing that runs in production.
    """

    def setUp(self) -> None:
        patch("brief_crew.validator_flow.lookup_branch_cache", return_value=[]).start()
        self.addCleanup(patch.stopall)
        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)

    def _drive(self, cap: int, replies: list[str]) -> dict[str, object]:
        """Run the durable pause/resume loop and report what happened."""
        factories, runners = _factories()
        scope, *_ = fixtures()
        asked: list[str] = []
        stamped: list[int] = []
        counts_per_resume: list[int] = []
        flow_id = "durable-gate-turns"

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH", Path(directory) / "v.md"
            ), patch("brief_crew.validator_flow.VALIDATOR_MAX_GATE_TURNS", cap):
                flow = ValidatorFlow(
                    persistence=self.store, crew_factories=factories
                )
                outcome = flow.kickoff(
                    inputs={"idea": scope.startup_idea, "id": flow_id}
                )
                last_flow = flow
                while isinstance(outcome, HumanFeedbackPending):
                    asked.append(outcome.context.method_name)
                    stamped.append(
                        int(outcome.context.metadata[GATE_REVISE_TURNS_METADATA_KEY])
                    )
                    if not replies:
                        break
                    resumed = ValidatorFlow.from_pending(
                        outcome.context.flow_id,
                        self.store,
                        crew_factories=factories,
                    )
                    last_flow = resumed
                    outcome = resumed.resume(replies.pop(0))
                    counts_per_resume.append(
                        max(resumed._method_call_counts.values(), default=0)
                    )

        return {
            "asked": asked,
            "stamped": stamped,
            "counts_per_resume": counts_per_resume,
            # What the STORE holds. This flow has no `@persist` step, so CrewAI
            # writes the state only when it pauses - which means the store is
            # one leg behind whatever the final resume did. That is exactly
            # right for asserting a bound applied at an earlier gate, and
            # exactly wrong for asserting the last thing that happened.
            "stored_state": self.store.load_state(flow_id) or {},
            # What the final resumed flow object ended up holding. The
            # complement of the above: use it for the last leg.
            "final_state": last_flow.state,
            "runners": runners,
            "outcome": outcome,
        }

    def test_the_cap_holds_across_resumes(self) -> None:
        """The one test this whole feature exists to pass.

        Cap 2, three revises at the scope gate, each answered through a fresh
        flow object built by ``from_pending()``. If the counter lived anywhere
        in memory the third revise would be honoured like the first two and the
        Scoper would run a fourth time; the assertion on ``scope`` call count
        is what catches that.
        """
        result = self._drive(cap=2, replies=[REVISE, REVISE, REVISE, APPROVE])

        self.assertEqual(
            result["asked"],
            ["confirm_scope", "confirm_scope", "confirm_scope", "review_verdict"],
        )
        # The turns-used stamp each gate carried when it opened: 0 before any
        # revise, then 1, then 2 - at which point the scope budget is gone. The
        # trailing 0 is the VERDICT gate opening with its own untouched budget,
        # which is what a per-gate bound is supposed to look like.
        self.assertEqual(result["stamped"], [0, 1, 2, 0])
        # Read out of the DATABASE, not off a flow object. Two revises spent,
        # the third recorded as refused, and the Scoper called three times
        # rather than four.
        stored = result["stored_state"]
        self.assertEqual(stored["scope_revise_turns"], 2)
        self.assertTrue(stored["scope_revise_capped"])
        self.assertEqual(len(result["runners"]["scope"].inputs), 3)

    def test_crewai_own_counter_never_sees_more_than_one_call(self) -> None:
        """The negative half: the in-process guard is blind on this path.

        Every resumed flow's ``_method_call_counts`` peaks at 1, however many
        replies preceded it. A bound built on that number would have permitted
        an unlimited revise loop while looking like it was doing something.
        """
        result = self._drive(cap=99, replies=[REVISE, REVISE, REVISE, APPROVE])
        self.assertEqual(result["counts_per_resume"], [1, 1, 1, 1])
        self.assertEqual(result["stored_state"]["scope_revise_turns"], 3)

    def test_the_stamped_count_survives_the_store(self) -> None:
        """The prompt's remaining-turn number is durable, not in-memory.

        ``PendingFeedbackContext.metadata`` is what ``service/registry.py``
        reads to decide whether this gate still offers Revise, and CrewAI
        persists it through ``to_dict``/``from_dict``. Reading it back out of
        the store is what proves a process restart between the gate opening and
        the operator answering does not silently restore a spent budget.
        """
        self._drive(cap=5, replies=[REVISE, REVISE])
        loaded = self.store.load_pending_feedback("durable-gate-turns")
        assert loaded is not None
        state_data, context = loaded
        self.assertEqual(state_data["scope_revise_turns"], 2)
        self.assertEqual(context.metadata[GATE_REVISE_TURNS_METADATA_KEY], 2)

    def test_the_verdict_gate_holds_its_own_budget_across_resumes(self) -> None:
        result = self._drive(cap=1, replies=[APPROVE, REVISE, REVISE, APPROVE])
        self.assertEqual(
            result["asked"],
            ["confirm_scope", "review_verdict", "review_verdict"],
        )
        # The capped conversion here IS the last thing the run does, and no
        # pause follows it, so the store never sees it - see `_drive`. The
        # final flow object is the honest place to read it.
        final = result["final_state"]
        self.assertEqual(final.scope_revise_turns, 0)
        self.assertEqual(final.verdict_revise_turns, 1)
        self.assertTrue(final.verdict_revise_capped)
        self.assertFalse(final.scope_revise_capped)
        # The one honoured revise and the original synthesis: two Synthesist
        # calls, the most expensive turn in the pipeline, and no third.
        self.assertEqual(len(result["runners"]["synthesis"].inputs), 2)
        # The store still proves the durable half - the honoured turn crossed a
        # resume boundary to get there.
        self.assertEqual(result["stored_state"]["verdict_revise_turns"], 1)


if __name__ == "__main__":
    unittest.main()


class MalformedGateEditTests(unittest.TestCase):
    """A bad edit must not destroy a paid run.

    Found by an adversarial probe: `route_scope` validated the operator's edited
    scope with a bare `model_validate`, inside the router, AFTER the gate had
    been durably answered. A mistyped value in a field the gate itself offered
    for editing - `assumptions: "5"` where a list belongs - raised there, and
    the run ended `failed` with no gate to retry, no recovery path, and an
    escalation-tier Scoper call already spent. The operator had been told
    `202 Accepted`.

    The decision is what the operator meant; the edit is how they expressed it.
    Losing the second is a client defect. Losing the run is ours.
    """

    @staticmethod
    def _bad_edit() -> str:
        """A COMPLETE scope with one mistyped field.

        The realistic shape: the client sends back the gate's own `fields` dump
        with one value the operator typed wrong. A two-key payload would fail on
        five "Field required" errors instead and would not exercise the case.
        """
        edited = fixtures()[0].model_dump()
        edited["assumptions"] = "5"
        return json.dumps({"decision": "approve", "scope": edited})

    def _flow_with_reply(self, reply: str) -> ValidatorFlow:
        scope, market, sentiment, feasibility, verdict, report = fixtures()
        factories = ValidatorCrewFactories(
            scope=lambda: FakeRunner(scope),
            market=lambda: FakeRunner(market),
            sentiment=lambda: FakeRunner(sentiment),
            feasibility=lambda: FakeRunner(feasibility),
            synthesis=lambda *_: FakeRunner(verdict),
            report=lambda *_: FakeRunner(report),
        )
        replies = [reply, '{"decision": "approve"}']

        def scripted(_provider: object, context: object, _flow: object) -> str:
            return replies.pop(0) if replies else '{"decision": "approve"}'

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "brief_crew.validator_flow.OUTPUT_PATH",
                Path(directory) / "output" / "validation.md",
            ), patch(
                "brief_crew.validator_flow.lookup_branch_cache", return_value=[]
            ), patch.object(ValidatorFeedbackProvider, "request_feedback", scripted):
                flow = ValidatorFlow(crew_factories=factories)
                flow.kickoff(inputs={"idea": scope.startup_idea})
        return flow

    def test_a_malformed_edit_drops_the_edit_not_the_run(self) -> None:
        flow = self._flow_with_reply(self._bad_edit())
        # The run reached the end rather than dying in the router.
        self.assertIsNotNone(flow.state.report)
        # The original scope survived; the bad edit was not applied.
        self.assertEqual(flow.state.scope.startup_idea, fixtures()[0].startup_idea)

    def test_the_reason_is_recorded_where_an_operator_can_see_it(self) -> None:
        flow = self._flow_with_reply(self._bad_edit())
        self.assertIn("the edit was not applied", flow.state.scope_edit_error)
        # It names the offending field, which is the actionable half.
        self.assertIn("assumptions", flow.state.scope_edit_error)
        # And not pydantic's schema dump plus docs URL.
        self.assertNotIn("https://errors.pydantic.dev", flow.state.scope_edit_error)

    def test_a_malformed_edit_costs_no_revise_turn(self) -> None:
        # Charging a turn for the client sending the wrong JSON type would
        # punish the wrong party.
        flow = self._flow_with_reply(self._bad_edit())
        self.assertEqual(flow.state.scope_revise_turns, 0)

    def test_a_well_formed_edit_is_still_applied(self) -> None:
        # The guard must not silently swallow good edits.
        scope = fixtures()[0]
        edited = scope.model_dump()
        edited["category"] = "Dental clinic scheduling"
        flow = self._flow_with_reply(
            json.dumps({"decision": "approve", "scope": edited})
        )
        self.assertEqual(flow.state.scope.category, "Dental clinic scheduling")
        self.assertEqual(flow.state.scope_edit_error, "")
