"""The `builder.flow/v1 -> v2` upgrade on read. The seam, and now the mapping.

Plan 15 D5 puts one pure, idempotent function between a stored row and
`BuilderDocument.model_validate`, so that every row written under an older
schema parses as the current one without a rewrite: the next save writes the
current schema, the row before it is left exactly as it was, and no migration
ever has to touch `builder_document_versions`.

**Stage 1 carried the seam and not the mapping (S1 ruling 5). Plan 03 D4
landed the mapping**, `_v1_to_v2` below, registered in `_UPGRADES` and nowhere
else - which is what the seam existed for.

> **One step is still outstanding and it is not this module's to take.**
> `upgrade_document` walks `_UPGRADES` only while the document's schema differs
> from `config.BUILDER_DOCUMENT_SCHEMA`, and that constant is still
> `builder.flow/v1`. So the mapping is registered, tested and inert. Moving the
> constant is a TWO-SUITE contract change: `frontend/src/types/builder.ts`
> declares `BUILDER_SCHEMA_ID = 'builder.flow/v1'` and
> `builderVocabulary.ts::normalise` refuses a vocabulary whose `schema_id` does
> not equal it, so flipping one side alone disables the whole palette with a
> sentence about a schema the author never typed. `tests/builder/test_upgrade.py`
> proves the walk end to end with the constant patched, so the day both halves
> move there is nothing here left to write.

The two call sites - `store._parse` and the import route - are the two doors a
stored or uploaded document comes through, and the mapping had to land in one
place rather than in both.

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

def _v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """A `builder.flow/v1` document at `builder.flow/v2` - 03 D4, FD2.

    **It sets the schema string and touches nothing else, and that is the whole
    mapping.** Not an oversight, and worth reading before anybody "completes"
    it: v2 grew the schema by ADDITION only, and every addition is either a new
    union arm or an optional field.

    * An agent carries `agent_id`, so it parses as the LIBRARY arm - which is
      the arm it always was. `role` is the other arm's discriminator and a v1
      document has none, so presence-discrimination gives the right answer with
      nothing to rewrite. Same for a crew on `crew_id` / `process`.
    * `state` is `None` when absent, `on_error` defaults to `fail`, `joins`
      keeps its `"all"` values, and `target_port` was already defaulted to `in`
      by `BuilderEdge` before v2 existed.
    * `budget`, `positions` and every id are untouched. A stored budget is
      still the price of this exact graph - the upgrade changed no node.

    **Nothing is filled in that the model would default**, which is what makes
    the second pass byte-identical: a mapping that wrote `"state": null` or
    `"on_error": "fail"` into every node would produce a dict that differs from
    its own input on the first pass and then agrees with itself on the second,
    and the idempotence test would pass while the purity claim - a stored row
    round-trips unchanged except for the schema string - quietly stopped being
    true. Idempotence is necessary and it is not sufficient.

    An earlier note in this module anticipated `llm: {model: <tier preset>}`
    being added here. It is deliberately NOT: the tier presets live in
    `config.py`, they move (3.7-flash -> 3.8-flash on 2026-09-04), and baking
    one into every upgraded document would freeze each row at whatever the
    preset was on the day it was read. A library node names a tier and resolves
    the model at compile time, which is the behaviour it already had.
    """

    return {**document, "schema": SCHEMA_V2}


#: One step per schema: `from` -> a function producing the document at the
#: NEXT schema. `upgrade_document` walks this until the document is at
#: `BUILDER_DOCUMENT_SCHEMA`, so a v1 row still upgrades the day v3 exists.
#:
#: Every mapping must return a NEW dict carrying its target `schema`, and must
#: be a no-op on a document already at that target, or the idempotence test
#: fails - which is the test doing its job.
_UPGRADES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    SCHEMA_V1: _v1_to_v2,
}


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
