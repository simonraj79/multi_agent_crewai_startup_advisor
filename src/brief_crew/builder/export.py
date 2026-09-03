"""What a builder document looks like the moment it leaves this service.

Plan 15 D1: an export is a document, not a backup. It carries the graph the
author drew and nothing that identifies them, their row, or anything they own -
so a `.builder.json` can be mailed, pasted into a ticket or imported by somebody
else without a credential, a server record or a skill going with it.

**The strip works on the RAW dict, before any schema validation, over KEY NAMES**
(S1 ruling 6). That is a different guarantee from the one the schema gives and
it is the one that matters here. `BuilderDocument` refuses a key it does not
know, so a parsed v1 document cannot carry `credential_id` today - but C1's v2
fields land in Stage 2, and a strip that reasoned from the schema would have to
be edited the same day or it would quietly export the first secret-bearing field
the schema learned. Naming the keys instead means the day `AgentConfig` grows
`credential_id` (ruling 8) this file already covers it, and the test that pins
it can be written now over a dict that carries every one of them.

Flowise gets the same property by recursion (`_removeCredentialId`,
`docs/flowise-notes.md` section 3); the masked URL shape `<origin>/************`
is theirs too (section 4). Where the two differ: Flowise walks the whole node
looking for one key, this walks for four key SHAPES and says, per node, what
was taken - because a document that opens green after losing its credentials
is worse than one that opens with three problems naming three nodes.

Nothing here reads a table. `strip_for_export` is pure so that
`tests/builder/test_export.py` can assert the property over a dict rather than
over a database, and `resolve_server` is the one seam a caller with the
`mcp_servers` table (plan 07) may use to fill the hint from the record.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import quote, urlsplit

from brief_crew.config import BUILDER_DOCUMENT_SCHEMA


#: Top-level keys the importer mints for itself. `id` and `version` are the
#: server's - `builder_api.parse` overwrites both on every ingress - `budget`
#: is a price against a ceiling that may have moved and is recomputed on the
#: next validate, and `user_id` is not a document key at all: it is listed so
#: a head row dumped WITH its metadata cannot carry an owner into a file.
EXPORT_DROPPED_KEYS: tuple[str, ...] = ("id", "version", "budget", "user_id")

#: The four key shapes, from plan 15 "Interfaces - Consumed" and ruling 6.
CREDENTIAL_KEY = "credential_id"
CREDENTIAL_KEY_SUFFIX = "_credential_id"
SERVER_KEY = "server_id"
SERVER_HINT_KEY = "server_hint"
SKILL_KEY = "skill_id"
SKILL_NAME_KEY = "skill_name"

#: Flowise's mask, verbatim, so a hint reads the same in both products.
MASKED_PATH = "************"

#: The sibling keys a server hint is read from when no resolver is given. A
#: v2 mcp node's config may spell any of these; a hint reads what is there and
#: leaves the rest `null`.
_HINT_LABEL_KEYS = ("server_label", "label")
_HINT_TRANSPORT_KEYS = ("transport",)
_HINT_URL_KEYS = ("server_url", "url")

#: `resolve_server(server_id) -> {label, transport, url} | None`.
ServerHintResolver = Callable[[str], Mapping[str, Any] | None]

_FILENAME_UNSAFE = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|]+')
_WHITESPACE = re.compile(r"\s+")
MAX_EXPORT_FILENAME_CHARS = 100
EXPORT_FILENAME_SUFFIX = ".builder.json"
DEFAULT_EXPORT_STEM = "workflow"


def _is_credential_key(key: str) -> bool:
    return key == CREDENTIAL_KEY or key.endswith(CREDENTIAL_KEY_SUFFIX)


def mask_url(url: Any) -> str:
    """`<scheme>://<host>[:<port>]/************`, or the bare mask.

    Built from `hostname` and `port` rather than from `netloc`, because a URL
    can carry `user:password@` before the host and a mask that kept the netloc
    would keep exactly the part that must not leave. The path and the query -
    where a token most often sits - are what the asterisks replace.
    """

    if not isinstance(url, str) or not url.strip():
        return MASKED_PATH
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return MASKED_PATH
    if not parts.scheme or not hostname:
        return MASKED_PATH
    origin = f"{parts.scheme}://{hostname}"
    if port is not None:
        origin = f"{origin}:{port}"
    return f"{origin}/{MASKED_PATH}"


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _server_hint(
    mapping: Mapping[str, Any],
    server_id: Any,
    resolve_server: ServerHintResolver | None,
) -> dict[str, Any]:
    """`{label, transport, url}` for a stripped server reference.

    The resolver wins when it answers, because the record is the truth and the
    config's sibling keys are at best a copy of it. An inbound `server_hint` is
    never trusted: a hand-edited file could put an unmasked URL there, so its
    `url` is masked again on the way through.
    """

    record: Mapping[str, Any] | None = None
    if resolve_server is not None and isinstance(server_id, str) and server_id:
        found = resolve_server(server_id)
        record = found if isinstance(found, Mapping) else None
    inbound = mapping.get(SERVER_HINT_KEY)
    inbound = inbound if isinstance(inbound, Mapping) else {}
    source: Mapping[str, Any] = record if record is not None else mapping
    label = _first_present(source, _HINT_LABEL_KEYS) or _first_present(inbound, ("label",))
    transport = _first_present(source, _HINT_TRANSPORT_KEYS) or _first_present(
        inbound, ("transport",)
    )
    url = _first_present(source, _HINT_URL_KEYS) or _first_present(inbound, ("url",))
    return {
        "label": label,
        "transport": transport,
        "url": mask_url(url) if url else None,
    }


def _scrub(
    value: Any,
    *,
    node_id: str | None,
    stripped: list[str],
    resolve_server: ServerHintResolver | None,
    top: bool = False,
) -> Any:
    """One subtree, copied, with every secret-bearing key handled by shape.

    `top` marks the document itself, where `nodes` is the one key walked with
    each entry's own id so a stripped reference can be attributed. Every other
    level - and every other top-level key - is walked with the id it was
    reached under, which for the document itself is none: a secret at the top
    level is still scrubbed, and attributed to nobody.
    """

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        # A URL beside a server reference is the server's address, and the
        # first version of this walk let it through untouched - with the
        # `user:password@` and `?token=` a real one carries. The masked copy in
        # the hint is the only form it leaves in; found by the byte-level
        # assertion in `tests/builder/test_export.py`, not by reasoning.
        beside_server = SERVER_KEY in value
        for key, item in value.items():
            name = key if isinstance(key, str) else str(key)
            if _is_credential_key(name):
                # A key that is ALREADY null is the schema's default, not a
                # secret: since S1 ruling 8 every agent node serialises with
                # `credential_id: null`, so noting the node on the key alone
                # reported every clean export as needing a credential (found
                # at integration, not by either branch's own suite).
                out[name] = None
                if item not in (None, ""):
                    _note(stripped, node_id)
            elif name == SERVER_KEY:
                out[name] = None
                out[SERVER_HINT_KEY] = _server_hint(value, item, resolve_server)
                if item not in (None, ""):
                    _note(stripped, node_id)
            elif beside_server and name in _HINT_URL_KEYS:
                continue
            elif name == SERVER_HINT_KEY:
                # Rewritten beside `server_id` above; a hint with no server
                # reference next to it is dropped rather than passed through
                # unmasked.
                continue
            elif name == SKILL_KEY:
                # Dropped, not nulled: the skill is re-resolved by
                # `skill_name`, which passes through as an ordinary key.
                continue
            elif top and name == "nodes" and isinstance(item, (list, tuple)):
                out[name] = [
                    _scrub(
                        node,
                        node_id=(
                            node.get("id")
                            if isinstance(node, Mapping) and isinstance(node.get("id"), str)
                            else None
                        ),
                        stripped=stripped,
                        resolve_server=resolve_server,
                    )
                    for node in item
                ]
            else:
                out[name] = _scrub(
                    item,
                    node_id=node_id,
                    stripped=stripped,
                    resolve_server=resolve_server,
                )
        return out
    if isinstance(value, (list, tuple)):
        return [
            _scrub(
                item,
                node_id=node_id,
                stripped=stripped,
                resolve_server=resolve_server,
            )
            for item in value
        ]
    return deepcopy(value)


def _note(stripped: list[str], node_id: str | None) -> None:
    if node_id is not None and node_id not in stripped:
        stripped.append(node_id)


def strip_for_export(
    raw: Mapping[str, Any],
    *,
    resolve_server: ServerHintResolver | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """The document with every secret-bearing reference removed, and who lost one.

    Returns `(document, needs_credentials)`. `needs_credentials` is the id of
    every node that had a credential or a server reference stripped, in
    document order, once each - the list the importer renders as a problem
    group so the file opens honest rather than green (D2). A node that lost
    only a `skill_id` is not in it: `skill_name` survives and is what the
    importer's own library resolves by.

    Pure. `raw` is not mutated and the result shares no container with it.
    Keys are matched anywhere under a node - `config`, a nested `llm`, an entry
    in a `tools` list - because the v2 schema puts them at more than one depth
    and this file must not have to know which.
    """

    if not isinstance(raw, Mapping):
        raise TypeError(
            f"a builder document is a mapping; this is {type(raw).__name__}"
        )
    stripped: list[str] = []
    kept = {
        (key if isinstance(key, str) else str(key)): value
        for key, value in raw.items()
        if (key if isinstance(key, str) else str(key)) not in EXPORT_DROPPED_KEYS
    }
    document = _scrub(
        kept,
        node_id=None,
        stripped=stripped,
        resolve_server=resolve_server,
        top=True,
    )
    return document, stripped


def nulled_reference_nodes(raw: Mapping[str, Any]) -> list[str]:
    """Node ids whose credential or server reference is PRESENT and empty.

    The evidence half of the import's `needs_credentials` (round 3, D-15-19),
    and the exact COMPLEMENT of what `strip_for_export` reports: `_scrub`
    notes a node when the key it found carried something
    (`if item not in (None, "")`), and this notes it when the key was there
    and did not. Between them every node carrying such a key falls in exactly
    one list, which is what lets the importer reason about a file whose keys
    the export has already nulled.

    Why it exists. The export nulls every credential key and records the node
    in the envelope; on re-import the strip therefore finds nothing to note,
    so the import derived an EMPTY list from a file that had just said three
    nodes lost a key, and the graph silently dropped from the author's key to
    the platform key. Reading the envelope alone is not the answer either - a
    file can say anything - so the import takes the intersection, and this is
    the half a file cannot forge: the nulled key has to actually be there.

    Present-and-empty, not merely absent. A node that never had a credential
    slot has no such key at all and is not a claim about anything; flagging it
    would put every input and output node in the list.

    Pure, and `raw` is not mutated. Keys are matched at any depth under a node
    for the same reason `_scrub` matches them there.
    """

    if not isinstance(raw, Mapping):
        raise TypeError(
            f"a builder document is a mapping; this is {type(raw).__name__}"
        )
    found: list[str] = []
    nodes = raw.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return found
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        if _has_empty_reference(node) and node_id not in found:
            found.append(node_id)
    return found


def _has_empty_reference(value: Any) -> bool:
    """True when some credential or server key under `value` is there and empty."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            name = key if isinstance(key, str) else str(key)
            if _is_credential_key(name) or name == SERVER_KEY:
                if item in (None, ""):
                    return True
                continue
            if _has_empty_reference(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_has_empty_reference(item) for item in value)
    return False


def export_envelope(
    raw: Mapping[str, Any],
    *,
    source_version: int,
    name: str | None = None,
    exported_at: datetime | None = None,
    resolve_server: ServerHintResolver | None = None,
) -> dict[str, Any]:
    """The D1 envelope, keys in the order the plan writes them.

    `export` is the document's OWN `schema` value (ruling 4), not a constant:
    a file written today says `builder.flow/v1`, and the importer accepts that
    and v2 by name, so a file exported before C1 lands still imports after it.
    """

    document, needs_credentials = strip_for_export(raw, resolve_server=resolve_server)
    stamp = exported_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    schema = document.get("schema")
    return {
        "export": schema if isinstance(schema, str) and schema else BUILDER_DOCUMENT_SCHEMA,
        "exported_at": stamp.isoformat(),
        "name": name if name is not None else document.get("name"),
        "source_version": int(source_version),
        "needs_credentials": needs_credentials,
        "document": document,
    }


def export_filename(name: Any) -> str:
    """`<name>.builder.json`, safe inside a quoted `filename=` parameter.

    A document name is author text up to `BUILDER_MAX_NAME_CHARS` and may hold
    anything - a quote, a backslash, a path separator, a control character -
    and each of those either breaks the header or is a filename the browser
    will refuse or, worse, honour. ASCII only, because the plain `filename=`
    parameter carries no encoding; the exact name travels beside it in
    `filename*` (see `export_content_disposition`). A name that sanitises to
    nothing gets a stable default.
    """

    text = name if isinstance(name, str) else ""
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _FILENAME_UNSAFE.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip(" .")
    if not text:
        text = DEFAULT_EXPORT_STEM
    return f"{text[:MAX_EXPORT_FILENAME_CHARS].rstrip(' .')}{EXPORT_FILENAME_SUFFIX}"


def export_content_disposition(name: Any) -> str:
    """The whole `Content-Disposition` value for a `.builder.json` download.

    Two filename parameters, per RFC 6266: `filename=` carries the ASCII-safe
    stem from `export_filename` for a client that reads only that, and
    `filename*=UTF-8''...` carries the document's EXACT name, percent-encoded,
    which every current browser prefers when both are present. That is what
    lets the envelope's `name` and the downloaded file's stem be the same
    string - the console derives one from the other - without putting a raw
    quote or a non-ASCII byte into a header. Control characters are the one
    thing dropped from the exact form too, because no filesystem takes them.
    """

    text = name if isinstance(name, str) else ""
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f").strip()
    exact = (text or DEFAULT_EXPORT_STEM)[:MAX_EXPORT_FILENAME_CHARS] + EXPORT_FILENAME_SUFFIX
    return (
        f'attachment; filename="{export_filename(name)}"; '
        f"filename*=UTF-8''{quote(exact, safe='')}"
    )


__all__: Sequence[str] = (
    "CREDENTIAL_KEY",
    "CREDENTIAL_KEY_SUFFIX",
    "EXPORT_DROPPED_KEYS",
    "EXPORT_FILENAME_SUFFIX",
    "MASKED_PATH",
    "SERVER_HINT_KEY",
    "SERVER_KEY",
    "SKILL_KEY",
    "SKILL_NAME_KEY",
    "ServerHintResolver",
    "export_content_disposition",
    "export_envelope",
    "export_filename",
    "mask_url",
    "nulled_reference_nodes",
    "strip_for_export",
)
