"""What a document is allowed to ask a model to do - plan 05, D7.

`config.py` owns the registry itself: it reads `data/models.json` at import,
derives `PRICES` from it and refuses a row over the price ceiling. This module
is the half that reads a DOCUMENT against that registry, and like every other
module in this package it **reports and never raises**: an author looking at a
canvas needs "these three nodes name a model this build cannot use", each one
selectable, not the first exception a validator happened to hit.

THREE CODES, and they are three different repairs rather than one refusal wearing
three hats:

* ``model-unknown`` - the id is not in the roster at all. Pick another model.
* ``model-over-ceiling`` - the id IS in the roster and its recorded price has
  since crossed the ceiling. Nothing the author did; the catalogue moved under a
  published document, and the fix is a `refresh_models.py` run rather than an
  edit to the graph. It is reachable only through the parameterised
  ``registry=`` argument and through a document published before a price change,
  which is exactly why it exists: `config.py` refuses such a row at import, so
  in a healthy build this code fires for stale data and for nothing else.
* ``model-lacks-capability`` - the model is fine and the PARAMETER is not. This
  is the one the inspector also gates client-side, and it is enforced twice on
  purpose: the widget disables the control, and this reports it anyway, so a
  stale client cannot smuggle in a parameter the compiler would silently drop.
  Silently-dropped parameters are what the gauntlet names as the single most
  infuriating competitor behaviour.

WHAT IS DELIBERATELY NOT GATED. ``supports_vision`` is recorded on every row and
gates nothing, because the control it would gate does not exist: `multimodal` is
CUT from `AuthoredAgentConfig` (deprecated at CrewAI 1.15.18, removed at 2.0), so
there is no field for a document to carry. The flag is still served, because the
picker shows it - an author choosing between two models wants to know which one
can read an image even when nothing here can ask it to yet.

No cost: this reads a document and a dict. No network, no model, no credential.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from brief_crew.builder.bounds import Problem, attachment_edges
from brief_crew.builder.document import (
    AuthoredAgentConfig,
    AuthoredCrewConfig,
    BuilderDocument,
    BuilderNode,
    LlmConfig,
)
from brief_crew.config import (
    MODEL_BY_ID,
    MODEL_PRICE_CEILING_IN,
    RegistryModel,
    registry_model,
)

#: A model id no registry row carries. The author picks another.
MODEL_UNKNOWN = "model-unknown"
#: A registry row whose recorded input price is over the ceiling. Not the
#: author's doing - see the module docstring.
MODEL_OVER_CEILING = "model-over-ceiling"
#: The model is in the roster; the parameter asked of it is not one it supports.
MODEL_LACKS_CAPABILITY = "model-lacks-capability"


def _llm_fields(node: BuilderNode) -> tuple[tuple[str, LlmConfig], ...]:
    """Every ``LlmConfig`` this node carries, paired with the field that holds it.

    The field name travels because the canvas anchors a problem to a control,
    and "this crew's manager runs on a model that is not in the roster" is a
    different sentence, and a different repair, from the same thing said about
    its planner.
    """

    config = node.config
    found: list[tuple[str, LlmConfig]] = []
    if isinstance(config, AuthoredAgentConfig):
        found.append(("llm", config.llm))
    elif isinstance(config, AuthoredCrewConfig):
        if config.manager_llm is not None:
            found.append(("manager_llm", config.manager_llm))
        if config.planning_llm is not None:
            found.append(("planning_llm", config.planning_llm))
    return tuple(found)


def _model_references(node: BuilderNode) -> tuple[tuple[str, str], ...]:
    """Every model id this node names, paired with the field naming it.

    A LIBRARY node names none. It carries a `tier`, and a tier resolves to one
    of `config.py`'s two presets - both of which are registry rows by
    construction, since `PRICES` is built from the registry and the presets are
    read out of it. Checking them here would be checking `config.py` against
    itself.

    ``retry.fallback_model`` is included, and it is the one that would otherwise
    escape: it is the model a node uses on its LAST attempt, which is precisely
    the attempt nobody exercises before publishing.
    """

    found: list[tuple[str, str]] = [
        (f"{field}.model", llm.model) for field, llm in _llm_fields(node)
    ]
    retry = getattr(node.config, "retry", None)
    fallback = getattr(retry, "fallback_model", None)
    if fallback:
        found.append(("retry.fallback_model", fallback))
    return tuple(found)


def _capability_problems(
    node: BuilderNode,
    field: str,
    llm: LlmConfig,
    model: RegistryModel,
    *,
    has_attachments: bool,
) -> list[Problem]:
    """The parameters this model cannot honour, one problem each.

    Each message names the model and the parameter, because the author's next
    action is to change one of the two and the sentence has to say which two.
    """

    problems: list[Problem] = []
    if llm.response_format == "json_object" and not model.supports_json_mode:
        problems.append(
            Problem(
                code=MODEL_LACKS_CAPABILITY,
                severity="error",
                message=(
                    f"{model.id} does not support JSON mode, so {field}.response_format "
                    "would be sent and dropped and this node would answer prose where the "
                    "graph expects an object. Pick a model with JSON mode, or ask for text"
                ),
                node_id=node.id,
                # C8's `field`: the control the author has to change. This code
                # blames a DIFFERENT one on the next node, which is exactly why
                # the client's one-string-per-code map cannot express it.
                field=f"{field}.response_format",
            )
        )
    if llm.reasoning_effort is not None and not model.supports_reasoning:
        problems.append(
            Problem(
                code=MODEL_LACKS_CAPABILITY,
                severity="error",
                message=(
                    f"{model.id} does not support reasoning, so {field}.reasoning_effort "
                    f"{llm.reasoning_effort!r} would be paid for in the request and ignored "
                    "in the answer. Clear it, or pick a reasoning model"
                ),
                node_id=node.id,
                field=f"{field}.reasoning_effort",
            )
        )
    if has_attachments and not model.supports_tools:
        problems.append(
            Problem(
                code=MODEL_LACKS_CAPABILITY,
                severity="error",
                message=(
                    f"{model.id} does not support tool calling, and this node has "
                    "attachments wired to it. Every attached tool would be unreachable at "
                    "run time. Detach them, or pick a tool-calling model"
                ),
                node_id=node.id,
                # The repair is on the CANVAS - detach an edge - or on this
                # control. Naming the model field is the half the inspector can
                # focus; the sentence carries the other half.
                field=f"{field}.model",
            )
        )
    return problems


def model_problems(
    document: BuilderDocument,
    *,
    registry: Mapping[str, RegistryModel] | None = None,
    ceiling_usd_per_m_input: float | None = None,
) -> list[Problem]:
    """Every model this document names that this build cannot serve as asked.

    `registry` and `ceiling_usd_per_m_input` are parameters rather than reads of
    `config.py` for one reason, and it is a testing reason worth stating: the
    live registry cannot contain an over-ceiling row (`config.py` refuses one at
    import), so `model-over-ceiling` would be unreachable and therefore untested
    without a way to hand this function a registry that has one. That is the
    same shape as `budget_problems`' `ceiling_usd` parameter and it is there for
    the same reason.
    """

    rows = MODEL_BY_ID if registry is None else registry
    ceiling = (
        MODEL_PRICE_CEILING_IN
        if ceiling_usd_per_m_input is None
        else ceiling_usd_per_m_input
    )
    attached_to = {edge.target for edge in attachment_edges(document)}

    problems: list[Problem] = []
    for node in document.nodes:
        for field, model_id in _model_references(node):
            model = _lookup(rows, model_id)
            if model is None:
                problems.append(
                    Problem(
                        code=MODEL_UNKNOWN,
                        severity="error",
                        message=(
                            f"{model_id!r} is not a model this build offers, so "
                            f"{field} names something no run could resolve. Pick one from "
                            "the model picker; the roster is at GET /api/builder/models"
                        ),
                        node_id=node.id,
                        # `_model_references` yields `llm.model`,
                        # `manager_llm.model` or `retry.fallback_model`, and all
                        # three are separate controls on one form.
                        field=field,
                    )
                )
                continue
            if model.cost_in > ceiling:
                problems.append(
                    Problem(
                        code=MODEL_OVER_CEILING,
                        severity="error",
                        message=(
                            f"{model.id} is priced at ${model.cost_in:.4f} per million input "
                            f"tokens, over the ${ceiling:.2f} ceiling. Its price moved after "
                            "this graph was saved; pick a cheaper model"
                        ),
                        node_id=node.id,
                        field=field,
                    )
                )

        for field, llm in _llm_fields(node):
            model = _lookup(rows, llm.model)
            if model is None:
                # Already reported as `model-unknown`. Reporting a capability
                # problem about a model nobody can name would be a second
                # sentence about one repair.
                continue
            problems += _capability_problems(
                node,
                field,
                llm,
                model,
                has_attachments=node.id in attached_to,
            )
    return problems


def _lookup(
    rows: Mapping[str, RegistryModel], model_id: str
) -> "RegistryModel | None":
    """A row by id, tolerating the prefix and the variant in either spelling.

    A document is supposed to carry a base slug and `ModelSlug` checks only its
    SHAPE, so `openrouter/` and `:nitro` both reach here in practice. Resolving
    them is what keeps a hand-edited document reporting `model-lacks-capability`
    about a real model rather than `model-unknown` about a spelling.
    """

    if rows is MODEL_BY_ID:
        return registry_model(model_id)
    name = str(model_id or "").strip().casefold()
    if not name:
        return None
    base = name.removeprefix("openrouter/")
    stem, separator, _ = base.rpartition(":")
    for candidate in (name, base, stem if separator and stem else base):
        found = rows.get(candidate)
        if found is not None:
            return found
    return None


def registry_document() -> dict[str, object]:
    """The whole roster as JSON - what `GET /api/builder/models` serves.

    `generated_at` and `source` travel with the rows because they are what a
    stale mirror is diagnosed FROM: a client holding an old copy can say when
    the roster it has was measured, which no amount of comparing prices would
    tell it.

    One function for the endpoint and for `scripts/emit_builder_fixtures.py`,
    so the served payload and the committed client fixture cannot describe the
    same row differently. R7 admits a client mirror only on the condition that
    a Python-generated fixture is byte-compared against it, and a mirror
    generated by a second serialiser would satisfy the letter of that while
    checking nothing.
    """

    from brief_crew import config as project_config

    return {
        "schema": project_config.MODEL_REGISTRY_SCHEMA,
        "generated_at": project_config.MODEL_REGISTRY_GENERATED_AT,
        "source": project_config.MODEL_REGISTRY_SOURCE,
        "ceiling_usd_per_m_input": project_config.MODEL_REGISTRY_CEILING_IN,
        "presets": dict(project_config.MODEL_PRESETS),
        "models": registry_payload(project_config.MODEL_REGISTRY),
    }


def registry_payload(models: Iterable[RegistryModel]) -> list[dict[str, object]]:
    """The roster as plain JSON, for the endpoint and the client fixture.

    One serialiser rather than two, so `GET /api/builder/models` and
    `frontend/tests/fixtures/models.json` cannot describe the same row
    differently - which is the failure R7 admits a client mirror only on the
    condition of preventing.
    """

    return [
        {
            "id": model.id,
            "name": model.name,
            "provider": model.provider,
            "context_window": model.context_window,
            "supports_tools": model.supports_tools,
            "supports_vision": model.supports_vision,
            "supports_json_mode": model.supports_json_mode,
            "supports_reasoning": model.supports_reasoning,
            "cost_in": model.cost_in,
            "cost_out": model.cost_out,
            "cost_in_max_endpoint": model.cost_in_max_endpoint,
            "speed_tier": model.speed_tier,
            "recommended_for": list(model.recommended_for),
        }
        for model in models
    ]
