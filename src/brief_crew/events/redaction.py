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
constructor. The plan's intent is met by the per-field names below
(`api_key`, `token`, `dsn`, `value` is deliberately not one - see the note on
`http_header` in `service/credentials.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "BUILDER_STATE_SLOT_PREFIX",
    "REDACTED",
    "SECRET_KEYS",
    "SECRET_KEY_SUFFIXES",
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
        "dsn",
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


def normalize_secret_key(key: Any) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def is_secret_key(key: Any) -> bool:
    raw = str(key)
    normalized = normalize_secret_key(raw)
    if normalized in SECRET_KEYS:
        return True
    if raw.startswith(BUILDER_STATE_SLOT_PREFIX):
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
