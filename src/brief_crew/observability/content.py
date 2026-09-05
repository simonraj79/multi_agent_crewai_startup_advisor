"""The content policy: what a value becomes on its way out of the process.

Contract section 8. The default is that no message text, no completion text, no
tool argument or result text and no user-entered text leaves here at all - what
goes instead is a fingerprint, a key list, a count and a character length, which
still answer "which prompt produced this" without storing the prompt.

Three rules, in this order, and the order is the point:

1. **Bound first.** Every string is cut to the same ceiling the frame
   serializer already uses, so a value that arrived bounded stays bounded and
   one that did not cannot grow the payload.
2. **Redact by KEY, using the list already in force.**
   `brief_crew.events.redaction.is_secret_key` is imported rather than
   re-implemented. That module's own docstring records what two separate lists
   cost the last time: one walk redacted and one did not, in the same frame.
3. **Scrub by SHAPE, over the text that survives.** A key that arrives as a
   *value* - pasted into an idea, echoed by a model, carried in a tool argument
   under an innocent name - is invisible to rule 2, because rule 2 reads the
   key. Rule 3 reads the string.

Rule 3 also compares against the values this process itself holds in
credential-shaped environment variables. Those are *compared*, never logged,
never returned into a message, and a match is replaced with the same `***`
marker every other walk in this repository writes.
"""

from __future__ import annotations

from hashlib import sha256
import os
import re
from typing import Any, Iterable, Mapping, Sequence

from brief_crew.events.models import MAX_MESSAGE_LENGTH
from brief_crew.events.redaction import REDACTED, is_secret_key


#: Nothing alphanumeric, `_` or `-` may precede a prefix for it to count.
#:
#: **This is the rule a UUID needed.** `fc-` is a Firecrawl prefix and a UUID
#: contains `fc-` about 1.5% of the time - `1a0bea14-ffb3-459d-b5fc-f714a76e…`
#: is a real run id from a paid proof run, and it reached Langfuse as
#: `…-b5***`, so `membership_check` read FAIL for a run whose data was
#: perfectly correct. A hex digit and a hyphen are both excluded here, which is
#: exactly the UUID case; a real key in JSON, a header or a URL is preceded by
#: a quote, a space, `=`, `:` or `/` and still matches.
#:
#: Mirrors `scripts/observability/_common.py:531,536` - the same two constants,
#: written out rather than imported, because a runtime package importing a
#: tooling script would be the wrong dependency direction and the scripts are
#: another owner's. `tests/observability/test_content_policy.py` asserts the two
#: agree.
CREDENTIAL_BOUNDARY = r"(?<![0-9A-Za-z_-])"

#: A Firecrawl key is `fc-` + 32 hex. The floor is below that so a shorter
#: future key still trips, and far above a UUID's 12-hex tail.
FC_MIN_HEX_CHARS = 20

#: The prefixes the contract names, plus the shape each one is followed by.
#: Deliberately a shape and not a list of hosts: the point of this rule is to
#: catch a credential nobody declared.
_KEY_SHAPES = re.compile(
    "(?:"
    # `fc-` is the ONLY prefix the boundary applies to, and that is a
    # narrowing of the tooling's rule made deliberately here.
    #
    # The boundary exists to stop a UUID being mangled, and a UUID contains
    # nothing but hex and hyphens - so `fc-` is the only one of these prefixes
    # that can occur inside one. Applying the boundary to the others buys
    # nothing and costs real detections: `gate-sk-or-v1-…` has its prefix
    # preceded by a hyphen, and under a blanket boundary a planted key inside
    # an id would survive. Measured - V-REVIEW's `e3_planted_key_probe.py`
    # plants exactly that, and a blanket boundary reported six leaking
    # conditions where there had been none.
    #
    # `scripts/observability/_common.py` applies the boundary to all of them
    # because it is a SCANNER over committed evidence, where a false negative
    # costs a warning nobody needed; this is a REDACTOR on the way out, where a
    # false negative is a disclosure. Same two constants, one narrower
    # application, stated rather than diverged silently.
    + r"(?<![0-9a-f])fc-[0-9a-f]{%d,}" % FC_MIN_HEX_CHARS
    + r"|(?:sk-or-|sk-lf-|pk-lf-|pcsk_|github_pat_|ghp_|gho_|ghs_|ghu_|AIza)"
    + r"[A-Za-z0-9_\-]{6,}"
    + ")"
)

#: A URL carrying userinfo - `scheme://user:password@host/...`. `DATABASE_URL`
#: is the one this application actually sets, and its NAME is invisible to
#: `is_secret_key`: `databaseurl` is in no list and ends in none of
#: `SECRET_KEY_SUFFIXES`, so the whole connection string - password included -
#: was on no comparison list at all. Selection is by the SHAPE of the value
#: rather than by adding one more name, so `REDIS_URL`, `AMQP_URL` and whatever
#: the next one is called are covered without an edit.
_URL_WITH_USERINFO = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://([^/@\s]+):([^/@\s]+)@")

#: Values shorter than this are not credentials, and treating them as such
#: would let a one-character environment variable blank out ordinary text.
_MIN_SECRET_VALUE_CHARS = 12

#: A password segment shorter than this is not worth comparing against: it is
#: as likely to be an ordinary word inside a sentence as a credential, and
#: blanking every occurrence of it would damage readable text for nothing.
_MIN_SECRET_SEGMENT_CHARS = 6

#: How many environment values are held for comparison. A bound rather than a
#: judgement about which variables matter: `is_secret_key` decides that, and it
#: is the same predicate the frame walks use.
_MAX_SECRET_VALUES = 64


def credential_values_in_environment() -> tuple[str, ...]:
    """Every credential-shaped value this process holds, for comparison only.

    Selection is by NAME and by SHAPE, and the second half is not decoration.

    By name: `events.redaction.is_secret_key`, the same predicate that already
    decides whether a frame key is redacted - so nothing here is a second list
    to keep in step with the first, and a credential variable added later is
    covered without an edit.

    By shape: a value that is a URL carrying userinfo. `DATABASE_URL` is the
    measured case - the name matches no rule the redaction list has, so the
    connection string and the password inside it were on no comparison list,
    and a driver's exception message quoting the DSN would have carried both
    out of the process. Both the whole URL and its password segment are held,
    because a message can quote either.

    The returned strings are secrets. They are used by `scrub_text` and
    `safe_message` and by nothing else, they never reach a message, a log line
    or a payload, and the exporter's error handling is written to name a
    variable at most.
    """

    values: list[str] = []
    for name, value in os.environ.items():
        if len(values) >= _MAX_SECRET_VALUES:
            break
        candidate = (value or "").strip()
        if not candidate:
            continue
        userinfo = _URL_WITH_USERINFO.match(candidate)
        if not (is_secret_key(name) or userinfo):
            continue
        if len(candidate) >= _MIN_SECRET_VALUE_CHARS:
            values.append(candidate)
        if userinfo:
            password = userinfo.group(2)
            if len(password) >= _MIN_SECRET_SEGMENT_CHARS:
                values.append(password)
    # Longest first, so a value that contains another is replaced whole.
    return tuple(sorted(set(values), key=len, reverse=True))


def scrub_text(text: str, secret_values: Sequence[str] = ()) -> str:
    """Rule 3: bound, then blank anything key-shaped or known-secret."""

    bounded = text[:MAX_MESSAGE_LENGTH]
    for secret in secret_values:
        if secret and secret in bounded:
            bounded = bounded.replace(secret, REDACTED)
    return _KEY_SHAPES.sub(REDACTED, bounded)


#: What a `statusMessage`, a terminal reason or an observation name is cut to.
#: The same 1024 the exporter used before this function existed, so nothing
#: about the payload's size changed - only what is in it.
MAX_MESSAGE_CHARS = 1024


def safe_message(
    value: Any, secret_values: Sequence[str] = (), *, limit: int = MAX_MESSAGE_CHARS
) -> str:
    """A human-readable string that is allowed to leave, on EITHER policy.

    Contract section 6 asks for an `ExceptionClass: redacted message` on a
    failure, so a `statusMessage` is the one class of string this exporter
    sends as text whatever `capture_content` says. That makes it the one place
    the content policy could be bypassed without anybody choosing to bypass it,
    and it was: an exception message is written by a provider's client library
    or by a tool, and a driver that names the DSN it could not reach, or an API
    client that echoes the key it was refused with, puts a credential into it
    with no key-shaped dictionary key anywhere for rule 2 to catch. Measured
    rather than reasoned: a planted `sk-or-v1-` value in a failing frame
    reached six observations and the trace output with capture OFF.

    Scrubbing happens over the WHOLE string and the bound is applied after,
    which is the opposite order from `scrub_text` and is deliberate here: cutting
    first can split a key so that the shape rule no longer matches it while most
    of it is still on the wire.
    """

    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    for secret in secret_values:
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return _KEY_SHAPES.sub(REDACTED, text)[:limit]


#: How long an identity value may be. An id, a role sentence or a node name;
#: anything longer is not an identifier and is bounded rather than sent.
MAX_IDENTITY_CHARS = 512


def safe_identity(
    value: Any, secret_values: Sequence[str] = (), *, limit: int = MAX_IDENTITY_CHARS
) -> str:
    """An ID on its way out: compared against real credentials, never guessed at.

    The one rule, and the reason it is not `safe_message`: **an identity value
    is scrubbed by EXACT VALUE, never by shape.** A run id, a node id, a call
    id, a workflow id, an agent role, a task name - these are the fields a
    reader joins on, and a heuristic that rewrites one silently breaks every
    join that depends on it.

    Measured: the paid `validator-live-2` run id
    `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` contains `fc-`, so the shape rule
    rewrote it to `…-b5***` on the trace metadata and the run span, and
    `membership_check` reported FAIL for a run whose export was otherwise
    perfect. About **1.5%** of UUIDs contain `fc-`, so this was a silent,
    recurring, one-in-sixty corruption of the primary key.

    The exact-value rule is kept and is unconditional: a value equal to, or
    containing, a credential this process actually holds is redacted wherever
    it appears. Shape is a heuristic; a value is a fact - and an id has no
    business looking like a key in the first place.
    """

    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    for secret in secret_values:
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text[:limit]


def scrub_value(
    value: Any,
    secret_values: Sequence[str] = (),
    *,
    depth: int = 0,
    max_depth: int = 4,
    max_items: int = 64,
) -> Any:
    """Rules 1-3 over an arbitrary already-bounded structure.

    Frames arrive from the serializer already clipped and already key-redacted,
    so this is a second pass rather than the first - which is exactly why it
    adds the shape rule and repeats the key rule instead of replacing it. A
    payload built here can also carry values the exporter itself composed, and
    those have been through no walk at all.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return scrub_text(value, secret_values)
    if depth >= max_depth:
        return REDACTED
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                out["__truncated__"] = True
                break
            name = str(key)[:128]
            out[name] = (
                REDACTED
                if is_secret_key(key)
                else scrub_value(
                    item,
                    secret_values,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_items=max_items,
                )
            )
        return out
    if isinstance(value, (list, tuple)):
        return [
            scrub_value(
                item,
                secret_values,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
            )
            for item in list(value)[:max_items]
        ]
    return scrub_text(str(value), secret_values)


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return "".join(f"{key}={_text_of(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return "".join(_text_of(item) for item in value)
    return str(value)


def character_count(value: Any) -> int:
    """How much text a value carries, whether or not the text is sent."""
    return len(_text_of(value))


def fingerprint(value: Any) -> str:
    """A stable sha256 over a value's text, for joining without storing.

    For a message list this is the role and the content in order, which is what
    contract section 4 asks of `prompt_fingerprint`: two runs of the same
    rendered prompt produce the same 64 characters, and the prompt itself never
    leaves. For anything else it is the same walk over whatever the value is,
    so one function answers `input_fingerprint` too.
    """

    return sha256(_text_of(value).encode("utf-8", "replace")).hexdigest()


def key_names(value: Any, limit: int = 64) -> list[str]:
    if isinstance(value, Mapping):
        return [str(key)[:128] for key in list(value.keys())[:limit]]
    return []


def describe(value: Any, *, prefix: str) -> dict[str, Any]:
    """The content-free description of a value: keys, characters, fingerprint.

    `prefix` names what is being described (`input`, `arg`, `output`) so one
    function serves the trace input, a tool's arguments and a tool's result,
    and a reader of the payload can tell which is which without a schema.
    """

    described: dict[str, Any] = {
        f"{prefix}_chars": character_count(value),
        f"{prefix}_fingerprint": fingerprint(value),
    }
    names = key_names(value)
    if names:
        described[f"{prefix}_keys"] = names
    return described


def content_or_description(
    value: Any,
    *,
    capture: bool,
    prefix: str,
    secret_values: Sequence[str] = (),
) -> Any:
    """The single decision point for every `input`/`output` field sent.

    One function rather than a branch at each call site, because the failure
    this guards against is one surface forgetting: this repository has already
    paid for a leak whose whole cause was two walks over one value where only
    one of them redacted.
    """

    if not capture:
        return describe(value, prefix=prefix)
    return scrub_value(value, secret_values)


def joined(values: Iterable[str]) -> str:
    return ", ".join(sorted({value for value in values if value}))


#: Detail keys whose value is part of the frame VOCABULARY rather than
#: something a person, a model or a web page wrote: a stage, a status, an
#: identifier, a node name, a routing decision. These pass through as text
#: under the default policy; every other string does not.
#:
#: An ALLOWLIST and not a denylist, and the direction is the whole argument. A
#: denylist of content-bearing keys fails OPEN - a frame kind added next month
#: with a new free-text field leaks it, silently, on the default policy. This
#: fails CLOSED: the same new field is described rather than sent, somebody
#: notices a fingerprint where they wanted a word, and the cost of the mistake
#: is a follow-up rather than a disclosure.
#:
#: Measured, not reasoned: the first end-to-end exercise of this exporter put a
#: user's own text and a planted credential into a tool observation's metadata,
#: through `query` and `notes`, on the default policy. Neither is here.
STRUCTURAL_STRING_KEYS: frozenset[str] = frozenset(
    {
        "agent_id",
        "agent_role",
        "band",
        "call_id",
        "decision_reason",
        "error_class",
        "error_type",
        "event_type",
        "finish_reason",
        "frame_kind",
        "from",
        "gate_id",
        "guardrail",
        "guardrail_type",
        "kind",
        "mode",
        "model",
        "node_id",
        "observation_role",
        "outcome",
        "port",
        "reason",
        "route",
        "run_id",
        "server",
        "skill",
        "skill_event",
        "stage",
        "status",
        "task_id",
        "task_name",
        "tool",
        "tool_status",
        "transport",
        "verdict",
    }
)

#: The structural keys that hold an IDENTIFIER, and therefore take the
#: exact-value rule instead of the shape heuristic. Everything else in
#: `STRUCTURAL_STRING_KEYS` - `reason`, `stage`, `status`, `outcome`, `route`,
#: `verdict` - is a vocabulary word that can also carry free text, and free
#: text is exactly where a credential hides.
#:
#: Named explicitly rather than derived, because the two halves want opposite
#: treatments and the cost of getting either wrong is asymmetric: a leak in a
#: `reason`, or a corrupted primary key in a `run_id`.
IDENTITY_STRING_KEYS: frozenset[str] = frozenset(
    {
        # The decision's list, verbatim.
        "agent_role",
        "app_session_id",
        "call_id",
        "graph_version",
        "node_id",
        "response_id",
        "run_id",
        "task_name",
        "tool",
        "user_id",
        "workflow_id",
        # Plus four that ARE the same identifiers under another key: CrewAI's
        # own UUIDs for the agent and the task, and the node id an edge frame
        # names as its source and port. A UUID is the shape the corruption was
        # measured on, so these are the ones most at risk of it.
        "agent_id",
        "from",
        "port",
        "task_id",
    }
)

#: A vocabulary value is a word, not a paragraph. Anything longer than this
#: under a structural key is described instead, because a key can be
#: structural and still be handed something enormous.
MAX_STRUCTURAL_CHARS = 256


def described_string(value: str) -> dict[str, Any]:
    """A string as its length and its hash: joinable, unreadable."""

    return {"chars": len(value), "sha256": fingerprint(value)}


def policy_details(
    details: Any,
    *,
    capture: bool,
    secret_values: Sequence[str] = (),
    depth: int = 0,
    key: str = "",
) -> Any:
    """One frame's details as the content policy allows them to leave.

    Under capture this is `scrub_value` - the whole structure, redacted by key
    and scrubbed by shape. Under the default policy it is the same walk with
    one extra rule: a string that is not vocabulary becomes its length and its
    hash. Numbers, booleans and the key names themselves always survive, which
    is what keeps an EVENT observation worth reading when its text does not
    leave.
    """

    if capture:
        return scrub_value(details, secret_values, depth=depth)
    if details is None or isinstance(details, (bool, int, float)):
        return details
    if isinstance(details, str):
        if key in STRUCTURAL_STRING_KEYS and len(details) <= MAX_STRUCTURAL_CHARS:
            if key in IDENTITY_STRING_KEYS:
                # An IDENTIFIER: exact-value only. The shape rule has no
                # business rewriting the field a reader joins on, and it did -
                # a paid run's `run_id` containing `fc-` arrived as `…-b5***`.
                return safe_identity(details, secret_values, limit=MAX_STRUCTURAL_CHARS)
            # A vocabulary word that can also hold free text - a `reason`, a
            # `status`, an `outcome`. Free text is where a credential hides, so
            # this half keeps the shape rule.
            return scrub_text(details, secret_values)
        return described_string(details)
    if depth >= 4:
        return REDACTED
    if isinstance(details, Mapping):
        out: dict[str, Any] = {}
        for index, (name, item) in enumerate(details.items()):
            if index >= 64:
                out["__truncated__"] = True
                break
            label = str(name)[:128]
            out[label] = (
                REDACTED
                if is_secret_key(name)
                else policy_details(
                    item,
                    capture=False,
                    secret_values=secret_values,
                    depth=depth + 1,
                    key=label,
                )
            )
        return out
    if isinstance(details, (list, tuple)):
        return [
            policy_details(
                item,
                capture=False,
                secret_values=secret_values,
                depth=depth + 1,
                key=key,
            )
            for item in list(details)[:64]
        ]
    return described_string(str(details))
