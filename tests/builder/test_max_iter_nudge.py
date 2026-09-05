"""The max-iter nudge reaches Google as a USER turn, and the guard that says when it stops.

Two halves, and neither is worth much without the other.

**The behaviour**, proved red then green against a scripted LLM double that
records the role of the last message at the moment of the call:
`handle_max_iterations_exceeded` appends an assistant turn, and with the hook
installed the model sees a `user` turn instead. With the hook unregistered the
same double records `assistant` - which is the request Google answers with
`400 "Requests ending with a model turn are not supported."` and the run
`a9887442` failed on, three times, after nine calls had billed.

**The guard**, which is the half that survives a CrewAI upgrade. The fix rests
on three facts about the installed package, and every one of them is read out of
the package here rather than trusted: that the nudge is still an ASSISTANT turn,
that the max-iter call still passes no `from_agent`, and that a provider's
`call()` still invokes the before-call hooks on the very list it then sends. Each
assertion fails with a sentence naming the CrewAI symbol that moved, and says
what to do about it.

No cost: a double, an `inspect.getsource` and a hook registration. No network, no
model, no credential.
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from crewai.hooks import (  # noqa: E402
    register_before_llm_call_hook,
    unregister_before_llm_call_hook,
)
from crewai.llms.base_llm import BaseLLM  # noqa: E402
from crewai.utilities.agent_utils import handle_max_iterations_exceeded  # noqa: E402
from crewai_core.printer import Printer  # noqa: E402

from brief_crew.builder.max_iter import (  # noqa: E402
    NUDGE_ROLE,
    install_max_iter_nudge,
    max_iter_nudge_installed,
    nudge_trailing_model_turn,
)

# Importing the runtime is what installs the hook in a real process, and this
# module asserts that rather than reaching for the installer itself.
import brief_crew.builder.runtime  # noqa: E402,F401


class _ScriptedLLM(BaseLLM):
    """A model that answers one fixed string and records what it was asked with.

    It invokes the before-call hooks the way a native provider does - the exact
    two lines `OpenAICompletion.call` runs, and the shape `BaseLLM`'s own
    docstring gives as the example - because that is the seam under test. The
    guard below reads the real provider's source and asserts this double has not
    drifted from it.
    """

    model: str = "openrouter/google/gemini-3.8-flash"
    seen_roles: list[str] = []

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        if from_agent is None and not self._invoke_before_llm_call_hooks(
            messages, from_agent
        ):
            raise ValueError("LLM call blocked by before_llm_call hook")
        self.seen_roles.append(str(messages[-1].get("role")))
        return "Final Answer: the answer"


def _exhaust(llm: _ScriptedLLM) -> list[dict[str, Any]]:
    """One max-iter exhaustion, through CrewAI's own helper."""

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a researcher."},
        {"role": "user", "content": "Find three things."},
    ]
    handle_max_iterations_exceeded(
        None,
        printer=Printer(),
        messages=messages,
        llm=llm,
        callbacks=[],
        verbose=False,
    )
    return messages


class TheNudgeReachesTheModelAsAUserTurn(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = _ScriptedLLM(model="openrouter/google/gemini-3.8-flash", seen_roles=[])

    def test_without_the_hook_the_model_is_asked_with_a_trailing_model_turn(self) -> None:
        """The defect itself, reproduced: this is the request Google 400s on."""

        self.assertTrue(
            unregister_before_llm_call_hook(nudge_trailing_model_turn),
            "the hook was not registered, so this test cannot prove it is what changes "
            "the role; importing brief_crew.builder.runtime is what installs it",
        )
        try:
            _exhaust(self.llm)
        finally:
            register_before_llm_call_hook(nudge_trailing_model_turn)
        self.assertEqual(self.llm.seen_roles, ["assistant"])

    def test_with_the_hook_the_model_is_asked_with_a_user_turn(self) -> None:
        _exhaust(self.llm)
        self.assertEqual(self.llm.seen_roles, [NUDGE_ROLE])
        self.assertEqual(NUDGE_ROLE, "user")

    def test_the_nudge_text_survives_the_rewrite(self) -> None:
        """Only the role moves. The sentence that asks for a final answer stays."""

        messages = _exhaust(self.llm)
        self.assertIn("final answer", str(messages[-1]["content"]).lower())

    def test_importing_the_builder_runtime_installed_it(self) -> None:
        self.assertTrue(max_iter_nudge_installed())
        # A second call is a no-op, so a module imported twice cannot register
        # the same hook twice and rewrite the same message twice.
        self.assertFalse(install_max_iter_nudge())

    def test_a_conversation_that_does_not_end_in_a_model_turn_is_untouched(self) -> None:
        """The hook is a no-op on every request that was never at risk."""

        messages = [{"role": "user", "content": "hello"}]

        class _Context:
            pass

        context = _Context()
        context.messages = messages  # type: ignore[attr-defined]
        nudge_trailing_model_turn(context)
        self.assertEqual(messages, [{"role": "user", "content": "hello"}])

    def test_a_shape_the_hook_does_not_recognise_is_left_alone(self) -> None:
        """Never raise here: a provider quirk must not become a refusal to run."""

        class _Context:
            pass

        for messages in ([], None, ["not a mapping"]):
            context = _Context()
            context.messages = messages  # type: ignore[attr-defined]
            self.assertIsNone(nudge_trailing_model_turn(context))


class TheCrewAIFactsThisRestsOn(unittest.TestCase):
    """Three readings of the installed package. Each names what moved."""

    def test_the_max_iter_nudge_is_still_an_assistant_turn(self) -> None:
        source = inspect.getsource(handle_max_iterations_exceeded)
        self.assertIn(
            'role="assistant"',
            source,
            "crewai.utilities.agent_utils.handle_max_iterations_exceeded no longer "
            "appends an assistant turn. If it now appends a user turn, DELETE "
            "brief_crew/builder/max_iter.py and this file - the package has fixed it. "
            "If it appends something else, re-measure against Google before trusting "
            "either.",
        )
        self.assertIn(
            "llm.call(",
            source,
            "crewai.utilities.agent_utils.handle_max_iterations_exceeded no longer "
            "calls the model itself, so the before_llm_call hook this repository "
            "registers is no longer on that path. Re-read the helper and re-site the "
            "fix; the alternative seam is wrapping the helper in the five modules "
            "that import it by value.",
        )

    def test_the_max_iter_call_still_passes_no_from_agent(self) -> None:
        """`from_agent=None` is what puts the call on the direct-call hook path."""

        source = inspect.getsource(handle_max_iterations_exceeded)
        call = source[source.index("llm.call(") :]
        self.assertNotIn(
            "from_agent",
            call[: call.index(")")],
            "crewai.utilities.agent_utils.handle_max_iterations_exceeded now passes "
            "from_agent to llm.call. BaseLLM._invoke_before_llm_call_hooks returns "
            "early when from_agent is not None, so the hook would still fire - but "
            "through the EXECUTOR's snapshotted list instead, and a hook registered "
            "after the executor was built would be missed. Re-check the install site.",
        )

    def test_a_native_provider_still_hooks_the_list_it_then_sends(self) -> None:
        from crewai.llms.providers.openai.completion import OpenAICompletion

        source = inspect.getsource(OpenAICompletion.call)
        self.assertIn(
            "self._invoke_before_llm_call_hooks(",
            source,
            "crewai.llms.providers.openai.completion.OpenAICompletion.call no longer "
            "invokes the before_llm_call hooks. Every OpenRouter model in this "
            "product is served through this class, so the nudge in "
            "brief_crew/builder/max_iter.py is now dead code - re-site it.",
        )
        hooked = source.index("self._invoke_before_llm_call_hooks(")
        self.assertIn(
            "formatted_messages",
            source[hooked : hooked + 120],
            "OpenAICompletion.call no longer hands `formatted_messages` to the hooks. "
            "The nudge rewrites the list it is given; if that is no longer the list "
            "sent to the provider, the rewrite reaches nothing.",
        )
        self.assertLess(
            hooked,
            source.index("_call_completions("),
            "OpenAICompletion.call now invokes the before_llm_call hooks AFTER the "
            "request is built, so a hook can no longer change what is sent.",
        )

    def test_nothing_else_in_the_executor_leaves_a_trailing_model_turn(self) -> None:
        """Why rewriting ANY trailing assistant turn is safe in this version.

        The nudge does not match on content, so this is the assertion that keeps
        it precise: in CrewAI 1.15.18 the max-iter helper is the only place that
        appends an assistant message and then calls the model without a user
        turn after it.
        """

        from crewai.agents import crew_agent_executor

        executor_source = inspect.getsource(crew_agent_executor)
        self.assertNotIn(
            'role="assistant"',
            executor_source,
            "crewai.agents.crew_agent_executor now appends an assistant turn of its "
            "own. Read it: if the appended turn is followed by a user turn before "
            "the next model call, nothing changes here. If it is not, the nudge in "
            "brief_crew/builder/max_iter.py would rewrite it too, and it must be "
            "narrowed to the max-iter sentence.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
