"""Regenerate `data/models.json` from OpenRouter's public catalogue.

    usage: refresh_models.py [--write] [--keep-ids ID ...] [--max 10]
                             [--catalogue PATH] [--registry PATH]

**It prints a unified diff and writes nothing** unless `--write` is passed. That
is the whole point of the script rather than a safety flag bolted on: a price
that moves has to become a visible line in a commit. This repository has
published a wrong number six times, never twice for the same reason, and every
one of them was a figure that changed while the prose describing it did not. A
diff cannot go stale.

**Exit codes.** 0 when the registry is already current, 1 when it is stale (or,
with `--write`, when it has just been rewritten), and **2 when a model in the
current registry has LEFT the filtered catalogue** - deprecated, withdrawn, or
newly over the ceiling. Two rather than one because that is not a refresh, it is
a roster that no longer exists, and a CI job should be able to tell "the price
of gpt-5-mini doubled" from "gpt-5-mini is gone".

**THE FILTER, and the one clause in it that is not housekeeping.**

    cost_in <= ceiling
    'tools' in supported_parameters
    id does not end :free or :batch
    provider != anthropic

`:batch` is the interesting one. Batch is a QUEUED lane - half price, and
unusable for a run with streaming frames and a human waiting at a gate. Dropping
ids that end `:batch` stops a batch row entering the registry as a model of its
own. It does **not** stop a human reading a batch price into a plain row, and
that is exactly what happened: plan 05's own price table quoted
`google/gemini-3.5-flash-lite` at $0.15/$1.25 and `google/gemini-3.8-flash` at
$0.375/$1.875 - both the `:batch` variant, both exactly half the headline, both
presented as evidence that `config.py`'s correct prices were stale. So
`_price_pair` below takes `pricing.prompt` and `pricing.completion` from the
PLAIN slug's own row and from nothing else, and `tests/test_refresh_models.py`
carries a catalogue fixture in which the plain and `:batch` rows of one model
both appear.

**WHAT IS PRESERVED ACROSS A REFRESH**, and why it has to be. Three fields on
each row are not in the public catalogue at all:

* `cost_in_max_endpoint` - the dearest endpoint serving that slug. It comes from
  `/models/{id}/endpoints`, one call per model, measured once at build time
  (plan 05 decision 6). Preserving it means a re-measured value survives a price
  refresh, and a stale one is VISIBLE as an unchanged number beside a changed
  headline - which is more useful than silently recomputing it.
* `speed_tier` - a curated word. The public catalogue publishes no throughput
  figure.
* `recommended_for` - the roles the picker groups on. A judgement about the
  roster, not a fact about a model.

No credential: `GET /api/v1/models` needs no key. It is the only network call in
this repository's scripts that does not.
"""

from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import sys
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO / "src"))

from brief_crew.config import (  # noqa: E402
    MODEL_PRICE_CEILING_IN,
    MODEL_REGISTRY_PATH,
    MODEL_REGISTRY_SCHEMA,
)

CATALOGUE_URL = "https://openrouter.ai/api/v1/models"

#: Providers refused outright, whatever they cost. The gauntlet's rule is
#: "never a frontier model, anywhere", and `anthropic` is the one whose whole
#: catalogue sits above the ceiling - keeping it as a name rather than relying
#: on the price filter is what makes the refusal legible in a diff.
REFUSED_PROVIDERS = frozenset({"anthropic"})

#: Routing variants that are not models. `:free` is rate-limited and can vanish;
#: `:batch` is a queued lane a gated run cannot use. See the module docstring.
REFUSED_VARIANTS = (":free", ":batch")

#: The three curated fields, carried across a refresh. See the module docstring.
PRESERVED_FIELDS = ("cost_in_max_endpoint", "speed_tier", "recommended_for")

DEFAULT_MAX_MODELS = 10


# --------------------------------------------------------------------------
# Reading the catalogue
# --------------------------------------------------------------------------
def _price_pair(row: Mapping[str, Any]) -> tuple[float, float] | None:
    """`(cost_in, cost_out)` per MILLION tokens from one catalogue row.

    The public resource gives a per-TOKEN price as a decimal string
    (`"0.0000003"`), so the conversion is x 1e6. The MCP's `get-model` gives the
    same fact as a display string (`"$0.3/M tokens"`) already per million. The
    two disagree in FORM and never in value; mixing them up is a factor of a
    million, which is loud. Mixing up a plain row and a `:batch` row is a factor
    of two, which is not - and is the mistake that actually happened.
    """

    pricing = row.get("pricing") or {}
    try:
        prompt = float(pricing["prompt"]) * 1_000_000
        completion = float(pricing["completion"]) * 1_000_000
    except (KeyError, TypeError, ValueError):
        return None
    return (prompt, completion)


def _admits(row: Mapping[str, Any], *, ceiling: float) -> bool:
    """The filter, as one predicate, so the script and its test share it."""

    model_id = str(row.get("id") or "")
    if not model_id or "/" not in model_id:
        return False
    if model_id.endswith(REFUSED_VARIANTS):
        return False
    if model_id.split("/", 1)[0] in REFUSED_PROVIDERS:
        return False
    if "tools" not in (row.get("supported_parameters") or ()):
        return False
    price = _price_pair(row)
    if price is None:
        return False
    return price[0] <= ceiling


def derive_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """One catalogue row as a C3 registry row, minus the three curated fields.

    ``supports_reasoning`` DEPARTS FROM C3 AS WRITTEN, and the departure is a
    measurement rather than a preference. C3 says the flag is
    "`reasoning.supported_efforts` non-empty". Measured 2026-09-04,
    `qwen/qwen3.7-flash` publishes `reasoning: {mandatory: false,
    default_enabled: true, supports_max_tokens: true}` and
    `deepseek/deepseek-r1` publishes `reasoning: {mandatory: true}` - neither
    carries `supported_efforts`, and BOTH carry `reasoning` in
    `supported_parameters`. Under the rule as written the registry would say
    `deepseek-r1` cannot reason, and `deepseek-r1` is on the roster *for*
    reasoning, mandatorily. So the flag is `reasoning in supported_parameters`,
    which agrees with all ten rows.

    That leaves a genuinely separate capability with no field: whether a model
    accepts a reasoning EFFORT LEVEL. Four roster rows do not
    (`reasoning_effort` is absent from their `supported_parameters`), and the
    inspector currently offers the control to all of them. Contract request, in
    plan 05's Status.
    """

    model_id = str(row["id"])
    parameters = set(row.get("supported_parameters") or ())
    modalities = set((row.get("architecture") or {}).get("input_modalities") or ())
    cost_in, cost_out = _price_pair(row) or (0.0, 0.0)
    return {
        "id": model_id,
        "name": str(row.get("name") or model_id),
        "provider": model_id.split("/", 1)[0],
        "context_window": int(row.get("context_length") or 0),
        "supports_tools": "tools" in parameters,
        "supports_vision": "image" in modalities,
        "supports_json_mode": bool(
            {"response_format", "structured_outputs"} & parameters
        ),
        "supports_reasoning": "reasoning" in parameters,
        "cost_in": _round_price(cost_in),
        "cost_out": _round_price(cost_out),
    }


def _round_price(value: float) -> float:
    """Six decimal places, which is one more than any published rate uses.

    `deepseek/deepseek-v4-flash` is $0.088606 per million, so five would round
    a real published figure. Rounding at all is to stop a float that came back
    from `0.0000003 * 1e6` serialising as `0.30000000000000004` and making a
    diff about nothing.
    """

    return round(value, 6)


# --------------------------------------------------------------------------
# Building the new registry
# --------------------------------------------------------------------------
def build_registry(
    catalogue: Iterable[Mapping[str, Any]],
    current: Mapping[str, Any],
    *,
    ceiling: float | None = None,
    keep_ids: Sequence[str] = (),
    max_models: int = DEFAULT_MAX_MODELS,
) -> tuple[dict[str, Any], list[str]]:
    """The refreshed registry, and the ids that have LEFT the filtered catalogue.

    The roster's MEMBERSHIP is not recomputed from the catalogue, and that is
    the decision this function is really making. Ranking 300-odd tool-capable
    models by weekly token volume and taking the top ten would make every
    refresh a silent roster change - a model an author had chosen on one node
    could vanish because something else got popular. So the current registry's
    ids are the roster, `--keep-ids` adds to it, and everything else about each
    row is refreshed from the catalogue. Adding or removing a model is a
    deliberate edit to `--keep-ids` plus a `--write`, which is a reviewable
    commit rather than a side effect.
    """

    limit = MODEL_PRICE_CEILING_IN if ceiling is None else ceiling
    rows = {str(row.get("id")): row for row in catalogue}
    admitted = {
        model_id: row for model_id, row in rows.items() if _admits(row, ceiling=limit)
    }

    held = {str(row["id"]): row for row in current.get("models", ())}
    wanted: list[str] = list(held)
    for model_id in keep_ids:
        if model_id not in wanted:
            wanted.append(model_id)

    departed = [model_id for model_id in wanted if model_id not in admitted]
    refreshed: list[dict[str, Any]] = []
    for model_id in wanted:
        source = admitted.get(model_id)
        if source is None:
            # A row already IN the registry is kept verbatim, so the diff shows
            # only what really changed and the non-zero exit is what carries the
            # news. Silently dropping it would turn "this model is gone" into
            # "these rows moved up by one".
            #
            # A `--keep-ids` id that is not in the registry and not admitted has
            # nothing to keep: it is a request for a model this product may not
            # use, and it is reported as departed rather than invented.
            if model_id in held:
                refreshed.append(dict(held[model_id]))
            continue
        derived = derive_row(source)
        previous = held.get(model_id, {})
        for field in PRESERVED_FIELDS:
            if field in previous:
                derived[field] = previous[field]
        derived.setdefault("cost_in_max_endpoint", derived["cost_in"])
        derived.setdefault("speed_tier", "balanced")
        derived.setdefault("recommended_for", [])
        # A refreshed headline can rise above a STALE max-endpoint figure, and
        # the invariant `config.py` asserts at import is max >= headline. Lift
        # it to the headline rather than leaving a registry that will not load,
        # so the diff shows a number that needs re-measuring instead of a boot
        # that fails.
        if float(derived["cost_in_max_endpoint"]) < float(derived["cost_in"]):
            derived["cost_in_max_endpoint"] = derived["cost_in"]
        refreshed.append(derived)

    if len(refreshed) > max_models:
        raise SystemExit(
            f"{len(refreshed)} models, and C3 admits at most {max_models}. "
            "Drop one from data/models.json before adding another"
        )

    updated = dict(current)
    updated["schema"] = MODEL_REGISTRY_SCHEMA
    updated["models"] = refreshed
    return updated, departed


def render(payload: Mapping[str, Any]) -> str:
    """The exact text `data/models.json` holds. LF, two-space, trailing newline."""

    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def diff(before: str, after: str, *, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def fetch_catalogue(url: str = CATALOGUE_URL) -> list[dict[str, Any]]:  # pragma: no cover
    """`GET /api/v1/models`. No key, and no key is the point - see the docstring."""

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["data"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true", help="overwrite data/models.json (default: diff only)"
    )
    parser.add_argument(
        "--keep-ids", nargs="*", default=[], metavar="ID", help="add these ids to the roster"
    )
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_MODELS, dest="max_models")
    parser.add_argument(
        "--catalogue",
        type=pathlib.Path,
        default=None,
        help="a recorded catalogue JSON instead of the live endpoint (for tests)",
    )
    parser.add_argument("--registry", type=pathlib.Path, default=MODEL_REGISTRY_PATH)
    args = parser.parse_args(argv)

    registry_path: pathlib.Path = args.registry
    current = json.loads(registry_path.read_text(encoding="utf-8"))
    if args.catalogue is not None:
        payload = json.loads(args.catalogue.read_text(encoding="utf-8"))
        catalogue = payload["data"] if isinstance(payload, dict) else payload
    else:  # pragma: no cover - the network path
        catalogue = fetch_catalogue()

    updated, departed = build_registry(
        catalogue,
        current,
        keep_ids=args.keep_ids,
        max_models=args.max_models,
    )

    before = render(current)
    after = render(updated)
    relative = str(registry_path).replace("\\", "/")

    if departed:
        # Printed BEFORE the diff, because it is the finding and the diff is
        # merely the evidence.
        print(
            "left the filtered catalogue: "
            + ", ".join(sorted(departed))
            + "\n  (withdrawn, no longer tool-capable, or newly over the "
            f"${MODEL_PRICE_CEILING_IN:.2f}/M input ceiling)",
            file=sys.stderr,
        )

    if before == after:
        print("data/models.json is current")
        return 2 if departed else 0

    print(diff(before, after, path=relative), end="")
    if args.write:
        registry_path.write_text(after, encoding="utf-8")
        print(f"wrote {relative}", file=sys.stderr)
    return 2 if departed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
