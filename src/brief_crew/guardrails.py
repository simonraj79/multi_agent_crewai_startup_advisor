"""The evaluator-optimizer gate on `writing_task` - agents/05-evaluator.md Option A.

Pattern 6 is a loop: generate -> judge -> regenerate on failure. `Process.sequential`
has no mechanism to send a task backwards, so the loop is closed by a **task
guardrail**, which hands the failure message back to the Writer and re-runs the
task. No fourth agent.

The cost split is the whole point of splitting this in two:

  * ``check_mechanics`` is a **callable**. Word counting and URL counting are
    arithmetic. It costs nothing and runs first, so the cheap check rejects
    before the expensive one is ever reached.
  * ``ATTRIBUTION_GUARDRAIL`` is a **string**. CrewAI's ``LLMGuardrail`` builds a
    throwaway ``Agent(role="Guardrail Agent")`` and calls ``.kickoff()``, so every
    evaluation is its own LLM call - pass or fail. Only the checks that genuinely
    need judgement are left in it.

⚠️ Exhaustion raises. When ``guardrail_max_retries`` runs out,
``Task._invoke_guardrail_function`` raises a plain ``Exception`` - there is no
best-effort passthrough, and under ``Process.sequential`` the run dies. That is
the right behaviour for a sourcing gate, but it is a choice, not a default.
"""

from __future__ import annotations

import re

from crewai.tasks.task_output import TaskOutput

# The same range writing_task states. A guardrail that permits more than the
# task's stated ceiling enforces nothing.
MIN_WORDS = 500
MAX_WORDS = 700
MIN_DISTINCT_URLS = 3

_URL_RE = re.compile(r"https?://[^\s\)\]<>\"']+")


def _word_count(text: str) -> int:
    return len(text.split())


def check_mechanics(output: TaskOutput) -> tuple[bool, str]:
    """Deterministic checks 1 and 5 from the evaluator checklist. Zero LLM calls.

    Returns ``(True, brief)`` to pass the validated text forward, or
    ``(False, message)`` to reject - the message goes back to the Writer as its
    retry instruction, so it says what to do, not merely what is wrong.
    """
    brief = output.raw or ""
    problems: list[str] = []

    words = _word_count(brief)
    if words > MAX_WORDS:
        problems.append(
            f"LENGTH: the brief is {words} words, over the {MAX_WORDS}-word ceiling. "
            f"Cut approximately {words - MAX_WORDS} words. Tighten existing sentences "
            f"and remove the weakest supporting detail - do not rewrite from scratch, "
            f"and do not drop a source to save words."
        )
    elif words < MIN_WORDS:
        problems.append(
            f"LENGTH: the brief is {words} words, under the {MIN_WORDS}-word floor. "
            f"If the analysis genuinely supported no more, say so explicitly in "
            f"'What this means' rather than padding with generalities."
        )

    urls = set(_URL_RE.findall(brief))
    if len(urls) < MIN_DISTINCT_URLS:
        problems.append(
            f"SOURCING: found {len(urls)} distinct URL(s); at least "
            f"{MIN_DISTINCT_URLS} are required. Carry the source URLs through from "
            f"the research notes into a '## Sources' list. Do not invent URLs to "
            f"reach the count - if the research did not supply three, that is an "
            f"upstream failure and the brief should say so."
        )

    if "## Sources" not in brief and "## sources" not in brief.lower():
        problems.append(
            "SOURCING: the brief has no '## Sources' section. Add one at the end, "
            "numbered, with publisher and URL. Nothing follows it."
        )

    if problems:
        return False, " | ".join(problems)
    return True, brief


# Checks 2 and 3 - attribution and faithfulness - genuinely need a model, because
# "is this claim traceable to a listed source" is a judgement, not arithmetic.
# Checks 1 and 5 are deliberately absent: check_mechanics already did them for free.
ATTRIBUTION_GUARDRAIL = """\
Reject the brief unless BOTH of the following hold:
  1. ATTRIBUTION - every numeric claim and every named-entity claim in the body
     is attributable to a source in the brief's own Sources list.
  2. FAITHFULNESS - the brief contains no fact, number, or example that is
     absent from the research notes and analysis it was given.
On rejection, state exactly which check failed and quote the specific claim or
sentence that caused it. Do not rewrite the brief yourself - return a verdict.
Judge only these two rules: style, tone, structure and how persuasive you find
the argument are out of scope. A brief that is honest about thin evidence is a
PASS; thin research is not the brief's failure."""
