"""The one list of key names whose values never leave the process in clear.

Two walks apply it and they used to disagree: `service/persistence.py` redacted
on the way to a row, so the database was clean, while `events/serializer.py`
bounded every frame and redacted nothing - so the live stream, `/frames` and
the NDJSON export, all served from the in-memory ring, carried whatever a tool
or an agent had put under `api_key`. A list restated in two modules is a list
that drifts, which is the whole reason it lives here and both import it.

Matching is on the NORMALISED key - lower-cased, non-alphanumerics dropped - so
`api_key`, `apiKey` and `API-Key` are all one entry. `x-api-key` is NOT: its
normalised form is `xapikey`, which is why that header name is its own entry
below (this docstring claimed otherwise until a test asked). The names
themselves are plan 01 D6's, plus the four this repository already redacted.

**And on a normalised SUFFIX, since 2026-09-03.** Exact matching let
`OPENROUTER_API_KEY`, `GITHUB_TOKEN`, `FIRECRAWL_API_KEY`, `PINECONE_API_KEY`,
`COHERE_API_KEY`, `auth_token` and `session_token` straight through - every
one a name this repository's own `.env` or a session library actually uses,
and none of them spelled the way the list expected. A key whose normalised
form ENDS in `key`, `token`, `secret`, `password` or `dsn` is now secret too,
with two carve-outs, each pinned by a test:

* The bare word must have something in front of it. `key` on its own is not
  redacted, because `key` is the NAME slot of every gate `derived` entry
  (`{"key": name, "value": ..., "kind": ...}` in `registry.py`), and `token`,
  `secret`, `password` and `dsn` alone are exact entries already.
* A builder state slot, `out__<node>`, is exempt from the suffix rule on its
  raw spelling. Node ids are the author's, may end in any word, and the value
  is a node's output - agent text, never a credential, because the document
  carries credential ids only (C5). Redacting `out__token` would have
  replaced that node's output with `***` in the persisted state and broken
  the resume that reads it.
* A name that ends in `key` because it NAMES a key rather than holding one is
  listed in `STRUCTURAL_KEY_NAMES` and is not secret. `body_key` is the one so
  far: an output node's config field, the name of the slot the node's body is
  written under. Builder document rows pass through `persistence._sanitize_json`
  on the way to the table, so the first cut of the suffix rule redacted it on
  the way in and every stored document with an output node came back as
  "stored in a shape this service no longer parses: unknown result body key
  '***'" - **107 assertions across eleven modules, and the E2E's first
  publish**, on a change whose own tests were green. `key` is the one suffix
  with two meanings in code; the other four have not needed this list.

Over-redaction is the accepted cost: a `donkey` or `hockey` key in somebody's
frame reads `***`, which hides a value, where the previous rule leaked one.

`headers` is broad on purpose. A mapping under that name is where a custom
HTTP tool's `Authorization` would sit, and a walk that descended into it
looking for known names would have to know every provider's spelling. The
whole value is replaced instead; nothing an operator needs to read lives there.

**`fields` is NOT here, and plan 01 D6 asks for it.** It is the gate
contract's own key - `pending_gate.fields` is the editable half of every gate
payload (`registry.py`, `persistence.py`, `RunStatusResponse`), and redacting
it by name turned every gate form into the string `***` and failed
`RunStatusResponse` validation on the first synthetic run. The vault's own
plaintext object is called `fields` too, but it never reaches a frame: it
lives in `ResolvedCredential`, whose `repr` hides it, and is handed to one
constructor. The plan's intent is met by the per-field names below - `api_key`, `token`,
`dsn` and, since 2026-09-04, `headervalue`. There is no second exclusion:
every name in `config.CREDENTIAL_FIELDS` is on this list except the ones
`config.CREDENTIAL_PUBLIC_FIELDS` declares to be labels, and
`tests/service/test_secret_redaction.py` derives its pin from that constant
rather than carrying one of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "BUILDER_STATE_SLOT_PREFIX",
    "REDACTED",
    "SECRET_KEYS",
    "SECRET_KEY_SUFFIXES",
    "STRUCTURAL_KEY_NAMES",
    "is_secret_key",
    "normalize_secret_key",
]

#: What a redacted value reads as, everywhere. `[REDACTED]` was the marker the
#: sanitiser wrote until 2026-09-03; plan 01 criterion 6 fixes the spelling at
#: `***` and one constant is how both walks stay on it.
REDACTED = "***"

SECRET_KEYS: frozenset[str] = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "ciphertext",
        "clientsecret",
        "cookie",
        # `db_uri` normalises to `dburi`, which ends in none of
        # SECRET_KEY_SUFFIXES - so until 2026-09-04 the NL2SQL tool's
        # constructor keyword was the one credential-bearing name in the builder
        # that reached a frame in clear. Found by plan 06's criterion 3 rather
        # than by review, which is the argument for asserting a redaction list
        # against the constructors that feed it instead of reading it.
        "dburi",
        "dsn",
        # An MCP stdio server's whole environment block (plan 07), and
        # 10 D2's fourth name. It ends in none of SECRET_KEY_SUFFIXES, so
        # nothing but an exact entry would have caught it - and the thing
        # inside it is a GITHUB_TOKEN in a shape the suffix rule cannot see,
        # because the rule reads the OUTER key. `headers` is here for the
        # same reason one line down.
        "env",
        # The `http_header` / `mcp_header` vault pair's SECRET half
        # (`config.CREDENTIAL_FIELDS`). It was spelled `value` until
        # 2026-09-04 and was therefore on no list and matched no suffix -
        # pinned as not-secret by the very test file that owns criterion 6
        # (D-01-6). The field was renamed rather than `value` added here,
        # because `value` is the gate `derived` entry's display slot, a
        # router branch's compare operand and a transform's argument: the
        # measurement is six red tests across four modules, three of them
        # gates. See the note beside `CREDENTIAL_FIELDS`.
        "headervalue",
        "headers",
        "nonce",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "setcookie",
        "token",
        "xapikey",
    }
)


#: A normalised key ENDING in one of these is secret, provided something comes
#: before it - see the module docstring for the two carve-outs and why.
SECRET_KEY_SUFFIXES: tuple[str, ...] = ("key", "token", "secret", "password", "dsn")

#: The raw prefix of a compiled builder graph's state slots (`runtime.py`
#: writes `out__<node id>`); the suffix rule does not apply to them.
BUILDER_STATE_SLOT_PREFIX = "out__"

#: Normalised names that end in `key` because they NAME a key and never hold
#: one. Checked before the suffix rule. The module docstring carries the
#: measured cost of leaving `body_key` off this list.
STRUCTURAL_KEY_NAMES: frozenset[str] = frozenset({"bodykey"})


def normalize_secret_key(key: Any) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def is_secret_key(key: Any) -> bool:
    raw = str(key)
    normalized = normalize_secret_key(raw)
    if normalized in SECRET_KEYS:
        return True
    if normalized in STRUCTURAL_KEY_NAMES or raw.startswith(BUILDER_STATE_SLOT_PREFIX):
        return False
    return any(
        normalized.endswith(suffix) and len(normalized) > len(suffix)
        for suffix in SECRET_KEY_SUFFIXES
    )


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """A shallow copy with every secret-named value replaced. For tests and
    for callers that already bound their input; the two walks inline the
    check because they recurse under their own limits."""

    return {
        str(key): REDACTED if is_secret_key(key) else item for key, item in value.items()
    }
