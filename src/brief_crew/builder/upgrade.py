"""The `builder.flow/v1 -> v2` upgrade on read. In Stage 1, the hook.

Plan 15 D5 puts one pure, idempotent function between a stored row and
`BuilderDocument.model_validate`, so that every row written under an older
schema parses as the current one without a rewrite: the next save writes the
current schema, the row before it is left exactly as it was, and no migration
ever has to touch `builder_document_versions`.

**This module carries the seam and not the mapping - S1 ruling 5.** The v2
schema (contract C1) is owned by plan 03, which is Stage 2, and
`BUILDER_DOCUMENT_SCHEMA` is still `builder.flow/v1`, so there is nothing to
upgrade *to*. What exists today is the place the mapping lands, the two schema
strings the importer accepts (ruling 4), and the property every later mapping
has to keep: `upgrade_document(upgrade_document(x)) == upgrade_document(x)`,
pinned by `tests/builder/test_upgrade.py` over every committed v1 fixture.

Why a hook that does nothing is still worth wiring now rather than the day it
has work to do: the two call sites - `store._parse` and the import route - are
the two doors a stored or uploaded document comes through, and a mapping that
lands with C1 must not have to find and edit both. It lands in `_UPGRADES`
below and nowhere else.

A document whose `schema` this service does not know is passed through
UNCHANGED, on purpose. `BuilderDocument._validate_schema` refuses it with a
sentence that names the schema and the one this service compiles; refusing it
here as well would be a second message for one fault, and the store's
`_parse` already wraps that message with the document's id.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from brief_crew.config import BUILDER_DOCUMENT_SCHEMA


#: The schema string every document in the database carries today.
SCHEMA_V1 = "builder.flow/v1"
#: Contract C1 (plan 03). Accepted by name so an export written under it is a
#: 422 that says "not yet" rather than one that says "unknown schema".
SCHEMA_V2 = "builder.flow/v2"

#: What the import route accepts as an envelope's `export` value - ruling 4.
KNOWN_SCHEMAS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2)

#: One step per schema: `from` -> a function producing the document at the
#: NEXT schema. `upgrade_document` walks this until the document is at
#: `BUILDER_DOCUMENT_SCHEMA`, so a v1 row still upgrades the day v3 exists.
#:
#: Empty in Stage 1. The v1 -> v2 mapping from 15 D5 - `tier` kept and
#: `llm: {model: <tier preset>}` added, `target_port` defaulted to `in`,
#: `joins` unchanged, `budget` dropped - is registered here by plan 03 when C1
#: lands and `BUILDER_DOCUMENT_SCHEMA` becomes SCHEMA_V2:
#:
#:     _UPGRADES[SCHEMA_V1] = _v1_to_v2
#:
#: Every mapping must return a NEW dict carrying its target `schema`, and must
#: be a no-op on a document already at that target, or the idempotence test
#: fails - which is the test doing its job.
_UPGRADES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def is_known_schema(value: Any) -> bool:
    """Whether `value` names a schema this service can read or will read."""

    return isinstance(value, str) and value in KNOWN_SCHEMAS


def upgrade_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `raw` at `BUILDER_DOCUMENT_SCHEMA`, or as close as the mappings reach.

    Pure: `raw` is never mutated and the result shares no containers with it,
    so a caller holding the stored row can compare before and after. Idempotent:
    a document already at the current schema comes back equal.

    Runs BEFORE schema validation and therefore over an untyped dict, which is
    the whole point - the mapping's job is to make an old shape parse, so it
    cannot be handed a parsed object. Nothing here validates; `_parse` does that
    next, with the document id in hand.
    """

    if not isinstance(raw, Mapping):
        raise TypeError(
            f"a builder document is a mapping; this is {type(raw).__name__}"
        )
    document: dict[str, Any] = deepcopy(dict(raw))
    # A missing key means the model's own default - today's schema - and is
    # left missing rather than filled in, so a stored row that never spelled it
    # round-trips byte-identical.
    schema = document.get("schema")
    visited: list[str] = []
    while schema != BUILDER_DOCUMENT_SCHEMA and schema in _UPGRADES:
        if schema in visited:
            # A mapping that hands back its own source schema would loop here
            # forever. A programming error in this module, named as one.
            raise RuntimeError(
                f"upgrade from {schema!r} did not advance the schema; "
                f"visited {visited}"
            )
        visited.append(schema)
        document = _UPGRADES[schema](document)
        schema = document.get("schema")
    return document


__all__: Sequence[str] = (
    "KNOWN_SCHEMAS",
    "SCHEMA_V1",
    "SCHEMA_V2",
    "is_known_schema",
    "upgrade_document",
)
