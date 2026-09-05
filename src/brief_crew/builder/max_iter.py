"""A trailing MODEL turn, rewritten as a user turn, at the one seam CrewAI exposes.

**The defect this exists for was found by spending money, not by a test.** Run
`a9887442-ff35-4da5-8974-52fa03e81a0f` (`benchmarks/paid-runs.md` defect 2)
failed three times over, after nine calls had already billed, with

```text
Error code: 400 - Provider returned error
  Google / Google AI Studio:
  "Requests ending with a model turn are not supported."   INVALID_ARGUMENT
```

**Cause, read out of the package rather than guessed.** When an agent's tool
loop reaches `max_iter`, `crewai.utilities.agent_utils`'s
`handle_max_iterations_exceeded` asks the model once more for a final answer -
and it asks by appending an **assistant** message and calling the LLM:

```python
messages.append(format_message_for_llm(assistant_message, role="assistant"))
answer = llm.call(messages, callbacks=callbacks)
```

Google's chat API refuses a request whose last message is a model turn. Both
model tiers in this product are Google-served (MISSION.md §6), so *any* agent
with tools that runs its loop to the cap fails - after the tool calls have
already been paid for.

**The seam, and why it is this one.** Three were available and two are worse:

* Subclassing `crewai.LLM` does not work at all. `LLM.__new__` is a factory: for
  a native provider it returns `native_class(...)` and ignores `cls`, so
  `LLM(model="openrouter/...")` is an `OpenAICompatibleCompletion` and a
  subclass of `LLM` is never instantiated. Measured, not assumed.
* Wrapping `handle_max_iterations_exceeded` means patching the name in the
  **five** modules that import it by value, and a sixth import site added
  upstream escapes the patch in silence.
* `crewai.hooks.register_before_llm_call_hook` is a documented public
  extension point whose contract is exactly this: *"Modify context.messages
  directly (in-place)"*. It reaches the max-iter call because that call passes
  no `from_agent`, so the provider's `call()` takes the direct-call branch and
  invokes `BaseLLM._invoke_before_llm_call_hooks(formatted_messages, None)` on
  the very list it then sends. It reaches every other call too, because an
  executor snapshots the global hook list when it is built.

**Why rewriting ANY trailing assistant turn is safe rather than merely
convenient.** In CrewAI 1.15.18 exactly one place in the whole executor stack
appends an assistant message and then calls the model without appending a user
turn after it, and that place is the max-iter nudge -
`grep -n 'role="assistant"' crewai/agents/crew_agent_executor.py
crewai/utilities/agent_utils.py` answers with `agent_utils.py:410` and nothing
else. `tests/builder/test_max_iter_nudge.py` pins that, and it is the test that
fails - naming the CrewAI symbol - on the day the package moves.

The rewrite is a **no-op** on every request that does not already end in a model
turn, and a request that does is one Google refuses. So this cannot change what
a working call sends; it can only stop a call that would have 400'd.

**It is registered globally, once, when `builder.runtime` is imported**, and
that is deliberate rather than incidental: the hook list is a module-level list
with no `ContextVar` in it, so it survives the worker threads CrewAI starts for
a streaming kickoff and for a fan-out branch, which a scoped hook does not. The
reach is wider than the builder - this repository's two hand-written flows are
Google-served too, and `VALIDATOR_BRANCH_MAX_ITER` is 2 - and that is a strict
improvement rather than a side effect worth hiding.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

__all__ = [
    "NUDGE_ROLE",
    "install_max_iter_nudge",
    "max_iter_nudge_installed",
    "nudge_trailing_model_turn",
]

LOGGER = logging.getLogger(__name__)

#: The role a trailing model turn is rewritten to. `user` and not `system`: the
#: nudge is an instruction to answer now, which is a thing the caller says, and
#: a second system turn late in a conversation is a shape some providers weight
#: very differently from the first.
NUDGE_ROLE = "user"

_installed = False


def nudge_trailing_model_turn(context: Any) -> None:
    """Rewrite a trailing assistant turn as a user turn, in place.

    The hook contract is `None`/`True` to allow the call and `False` to block
    it, so this returns `None` always: a message shape this does not recognise
    is left exactly as it was and the call goes ahead. Failing here would turn a
    provider quirk into a refusal to run at all.
    """

    messages = getattr(context, "messages", None)
    if not isinstance(messages, list) or not messages:
        return None
    last = messages[-1]
    if not isinstance(last, Mapping) or last.get("role") != "assistant":
        return None
    # A NEW mapping assigned into the same list, never a mutation of the
    # message itself: the executor keeps this list as its own conversation
    # history, and rewriting the object in place would change what the agent
    # believes it said as well as what this one request carries.
    messages[-1] = {**dict(last), "role": NUDGE_ROLE}
    LOGGER.debug(
        "rewrote a trailing model turn as a %s turn before the model call", NUDGE_ROLE
    )
    return None


def install_max_iter_nudge() -> bool:
    """Register the hook once per process. Returns whether it registered now."""

    global _installed
    if _installed:
        return False
    from crewai.hooks import register_before_llm_call_hook

    register_before_llm_call_hook(nudge_trailing_model_turn)
    _installed = True
    return True


def max_iter_nudge_installed() -> bool:
    """Whether this process has registered the hook."""

    return _installed
