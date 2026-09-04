"""What a builder graph costs before it runs, and whether that is allowed.

A user-authored graph has to be STATICALLY PRICEABLE. That is not a nicety: the
premise every earlier admission control rested on - "human inaction is the de
facto spend cap" - stopped being true when MAX_RUN_COST_USD landed, and it was
never true of a graph somebody else drew. So the estimate here is computed at
compile time, stored on the document, and read by admission; a graph whose worst
case does not fit under the per-run ceiling is refused before it can take a
queue slot.

THE MODEL, and every term in it is measured rather than assumed. Calibration is
the first paid run: 11 calls, 128,069 tokens, 46,787 of them completion, so
4,253 completion tokens per call. For each billable node,

    prompt      = GRAPH_BUDGET_SEED_PROMPT_TOKENS + depth x 4,253
    attempts    = guardrail_max_retries + 1
    tool calls  = max_iter + 1 if the node binds tools, else 1
    calls       = attempts x tool calls, x (1 + MAX_CYCLE_ITERATIONS) on a cycle
    usd        += calls x compute_cost_usd(the NODE's model, prompt, 4,253)

`depth` is the node's own longest billable-upstream depth rather than an
average, because a 20-deep chain costs 3.9x per call what a 1-deep one does and
an average would under-price exactly the shape that gets expensive.

TWO THINGS IT IS HONEST ABOUT.

1. It is an ESTIMATE OF A WORST CASE, not a forecast. Every node is priced as
   if every guardrail retried, every tool loop ran to `max_iter`, and every
   cycle went round MAX_CYCLE_ITERATIONS times. A real run of the validator's
   own shape prices at about a third of what the same shape's worst case does.
2. It inherits `compute_cost_usd`'s blind spots wholesale - embeddings, rerank
   and Firecrawl raise no LLM event and are absent from both - and adds one of
   its own: `:nitro` routes on speed, not price, so a nitro id's published rate
   is a floor. Since plan 05 the inflation is the registry's MEASURED
   `cost_in_max_endpoint / cost_in` for that slug, with NITRO_PRICE_FACTOR as a
   floor rather than as the whole answer - the measured per-model ratios run
   1.0x to 9.5x and one constant was never going to be right for ten rows.
   `floor_cost_usd` keeps the un-inflated figure beside the enforced one so the
   two can be told apart.

WHICH MODEL A NODE IS PRICED AT changed with plan 05 and is `node_model` below:
an AUTHORED node is priced at the model it names, a LIBRARY node at its tier's
preset. Before that every node was priced at its tier, which made the model
picker a control with no effect on the meter beside it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from brief_crew.builder.bounds import (
    Problem,
    back_edges,
    billable_depths,
    member_edges,
    member_of,
    nodes_on_cycles,
)
from brief_crew.builder.document import (
    AuthoredCrewConfig,
    LibraryAgentConfig,
    BuilderBudget,
    BuilderDocument,
    BuilderNode,
)
from brief_crew.config import (
    CHEAP_MODEL,
    OPENROUTER_MODEL_PREFIX,
    ESCALATION_MODEL,
    GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
    GRAPH_BUDGET_SEED_PROMPT_TOKENS,
    GRAPH_STATIC_BUDGET_MARGIN,
    MAX_CYCLE_ITERATIONS,
    MAX_RUN_COST_USD,
    NITRO_PRICE_FACTOR,
    compute_cost_usd,
)

BUDGET_OVER_CEILING = "budget-over-ceiling"
BUDGET_UNPRICED_MODEL = "budget-unpriced-model"

_MODEL_BY_TIER = {"cheap": CHEAP_MODEL, "escalation": ESCALATION_MODEL}


def node_model(node: BuilderNode) -> str:
    """The model id this node's calls are priced at - PER NODE, not per tier.

    Two arms, and the split is the same one `document.py` draws. A LIBRARY node
    names one of `config.py`'s YAML agents or crews, whose LLMs are built inside
    the crew from the tier constants; the document's `tier` word is the whole of
    what it gets to say, and pricing it any other way would be pricing a model
    the run will not use. An AUTHORED node carries `llm.model`, an id out of the
    registry, and that is what it will actually be billed at - so a graph that
    puts a classifier on `qwen/qwen3.7-flash` is priced at $0.03/M rather than
    at the cheap preset's $0.30/M, which is a 10x difference in the meter the
    author is watching.

    The spelling returned is a `PRICES` key. `resolve_price_model` accepts all
    four, but building the prefixed one here keeps the `:nitro` question (D5,
    below) answerable from one string.
    """

    config = node.config
    llm = getattr(config, "llm", None)
    if isinstance(config, AuthoredCrewConfig):
        # An authored crew's own step is the manager's call when there is one,
        # and otherwise the tier it declared. `manager_llm` is the model that
        # actually runs the hierarchical process; `planning_llm` runs at most
        # once and is not what the node's call count multiplies.
        llm = config.manager_llm
    if llm is not None and getattr(llm, "model", None):
        return _prefixed(str(llm.model))
    return _MODEL_BY_TIER[node.tier or "cheap"]


def _prefixed(model: str) -> str:
    """One model id in the spelling `PRICES` is keyed on."""

    return (
        model
        if model.startswith(OPENROUTER_MODEL_PREFIX)
        else f"{OPENROUTER_MODEL_PREFIX}{model}"
    )


def fallback_model(node: BuilderNode) -> str | None:
    """The model a node's LAST retry attempt would use, if it declares one.

    09 D4: a fallback is priced at the DEARER of the two, so the static estimate
    stays a worst case. Pricing it at the named model would under-price exactly
    the node an author gave a fallback to because they expected it to fail.
    """

    retry = getattr(node.config, "retry", None)
    model = getattr(retry, "fallback_model", None)
    return _prefixed(str(model)) if model else None


def _nitro_multiplier(model: str) -> float:
    """What a `:nitro` id may bill above its published rate, as a factor.

    D5, narrowed by the 2026-09-04 endpoint measurement. `:nitro` routes on
    SPEED, not price, so a nitro id's published rate is a floor and the dearest
    endpoint serving that slug is what it can actually cost. Where the registry
    records that endpoint the factor is `max(measured, NITRO_PRICE_FACTOR)` -
    the measurement, with the constant as a floor so a re-measure that came back
    suspiciously low cannot quietly reduce the enforced figure.

    A PLAIN id gets 1.0, and that is a decision the measurement now supports
    rather than an omission. Applying 1.8 to a plain id would invent a number in
    both directions: the three OpenAI first-party rows spread 1.1x and
    `openai/gpt-oss-120b` spreads 9.5x, so one constant is wrong for nine of the
    ten rows. A plain slug is not routed on speed, so its headline is what it
    bills.
    """

    if ":nitro" not in model.casefold():
        return 1.0
    from brief_crew.config import registry_model

    row = registry_model(model)
    if row is None or row.cost_in <= 0:
        return NITRO_PRICE_FACTOR
    return max(row.cost_in_max_endpoint / row.cost_in, NITRO_PRICE_FACTOR)


@dataclass(frozen=True)
class NodeCost:
    """What one billable node contributes to the graph's static price."""

    calls: int
    usd: float
    model: str


@dataclass(frozen=True)
class BudgetEstimate:
    """The static price of one graph, and the counts that produced it."""

    # What admission enforces: the floor price with NITRO_PRICE_FACTOR applied
    # to every cheap-tier node.
    static_cost_usd: float
    # The same graph at the PUBLISHED prices, with no nitro inflation. Kept
    # beside the enforced figure because the two answer different questions -
    # this one is comparable with a `compute_cost_usd` total from a real run,
    # and the one above deliberately is not.
    floor_cost_usd: float
    # Model calls the worst case makes. The unit the frontier was solved in.
    modelled_calls: int
    billable_nodes: int
    escalation_nodes: int
    cycles: int
    # Tiers whose model `PRICES` cannot price. Never empty-and-ignored: an
    # unpriced model contributes nothing to the total, so treating it as an
    # error is the only thing standing between "no price on file" and "this
    # graph is free" - the exact confusion that reported a 128,069-token run at
    # $0.00.
    unpriced_models: tuple[str, ...] = ()
    # Per-node calls and dollars, requested by 04 for the inspector's cost line
    # (C5). It is the SAME figure the total already sums, exposed rather than
    # recomputed on the client - R6 stands: the client renders it and never
    # derives it, because two arithmetics for one number is how a meter and a
    # refusal come to disagree.
    per_node: Mapping[str, "NodeCost"] = field(default_factory=dict)

    def as_budget(self, *, compiled_at: datetime | None = None) -> BuilderBudget:
        """The block the compiler writes onto the document it priced."""

        return BuilderBudget(
            static_cost_usd=self.static_cost_usd,
            billable_nodes=self.billable_nodes,
            escalation_nodes=self.escalation_nodes,
            cycles=self.cycles,
            compiled_at=compiled_at or datetime.now(timezone.utc),
        )


def _calls_for(node: BuilderNode, *, on_cycle: bool, members: int = 0) -> int:
    """The worst-case model calls one billable node makes.

    Three multiplied terms, and each is the answer to a real question. Every
    guardrail retries (CrewAI counts retries PER guardrail). Every tool loop
    runs to `max_iter` - but only if the node binds tools at all, because an
    agent with none makes one call per attempt and pricing it as if it looped
    would inflate the cheapest kind of node there is. A crew is priced as
    tool-using whatever it declares, since the document cannot see what its
    agents bind and the conservative answer is the safe one.
    """

    if not node.is_billable:
        return 0
    config = node.config
    attempts = getattr(config, "guardrail_max_retries", 0) + 1
    # Narrowed to the LIBRARY arm on purpose. An AUTHORED agent carries no
    # `tools` tuple at all - its attachments are `attach` edges - so there is
    # nothing here to read, and the conservative answer for a node whose hands
    # this function cannot see is the same one a crew already gets: price it as
    # tool-using. Under-pricing is the failure that reported 128,069 real tokens
    # at $0.00.
    binds_tools = not isinstance(config, LibraryAgentConfig) or bool(config.tools)
    calls = attempts * ((getattr(config, "max_iter", 1) + 1) if binds_tools else 1)
    # 09 D4: the WHOLE-NODE retry loop multiplies everything above it, because
    # `run_agent` re-runs the entire step - the agent, its task and every
    # guardrail attempt inside it. `retry.max_retries` is the builder's own
    # field and is NOT `Task.max_retries`, which is deprecated at 1.15.18 and
    # counts guardrail retries; `guardrail_max_retries` above is the one that
    # means what CrewAI's means.
    retry = getattr(config, "retry", None)
    calls *= int(getattr(retry, "max_retries", 0) or 0) + 1
    if isinstance(config, AuthoredCrewConfig) and members:
        # An authored crew runs ONE TASK PER MEMBER, so its step is `members`
        # times what a single agent's is. A hierarchical process adds the
        # manager, which makes one call per task to delegate it - so a
        # hierarchical crew of three prices three manager calls that a
        # sequential crew of three does not.
        calls *= members
        if config.process == "hierarchical":
            calls += members * (1 + MAX_CYCLE_ITERATIONS if on_cycle else 1)
    if on_cycle:
        calls *= 1 + MAX_CYCLE_ITERATIONS
    return calls


def node_call_count(document: BuilderDocument, node_id: str) -> int:
    """`_calls_for` addressed by node id, for a caller holding only the id.

    It is the term an author can actually act on: a node's price is dominated
    by its retry ceilings and by whether it sits on a cycle, not by anything
    about the prompt.
    """

    node = document.nodes_by_id().get(node_id)
    if node is None:
        return 0
    return _calls_for(
        node,
        on_cycle=node_id in nodes_on_cycles(document),
        members=_member_counts(document).get(node_id, 0),
    )


def _member_counts(document: BuilderDocument) -> dict[str, int]:
    """How many member agents each crew holds - what its task list will be."""

    counted: dict[str, int] = {}
    for edge in member_edges(document):
        counted[edge.target] = counted.get(edge.target, 0) + 1
    return counted


def estimate_budget(document: BuilderDocument) -> BudgetEstimate:
    """Price the whole graph at its worst case. Never raises."""

    depths = billable_depths(document)
    cyclic = nodes_on_cycles(document)
    members = _member_counts(document)
    # A member agent is billable INSIDE its crew - the crew's price multiplies
    # by its membership above - and counting it again would charge the same
    # agent twice.
    inside_a_crew = set(member_of(document))

    static = 0.0
    floor = 0.0
    calls_total = 0
    billable = 0
    escalation = 0
    unpriced: list[str] = []
    per_node: dict[str, NodeCost] = {}

    for node in document.nodes:
        if not node.is_billable or node.id in inside_a_crew:
            continue
        billable += 1
        tier = node.tier or "cheap"
        if tier == "escalation":
            escalation += 1

        calls = _calls_for(
            node, on_cycle=node.id in cyclic, members=members.get(node.id, 0)
        )
        calls_total += calls

        prompt_tokens = (
            GRAPH_BUDGET_SEED_PROMPT_TOKENS
            + depths.get(node.id, 0) * GRAPH_BUDGET_CALL_COMPLETION_TOKENS
        )
        # The DEARER of the named model and its fallback (09 D4). A fallback is
        # what the last attempt uses, so a node that declares an expensive one
        # can cost that much; pricing it at the cheap one it usually uses would
        # under-price exactly the node the author expected to fail.
        candidates = [node_model(node)]
        alternative = fallback_model(node)
        if alternative and alternative not in candidates:
            candidates.append(alternative)

        priced: list[tuple[float, float, str]] = []
        for candidate in candidates:
            per_call = compute_cost_usd(
                candidate, prompt_tokens, GRAPH_BUDGET_CALL_COMPLETION_TOKENS
            )
            if per_call is None:
                if candidate not in unpriced:
                    unpriced.append(candidate)
                continue
            priced.append((per_call * _nitro_multiplier(candidate), per_call, candidate))
        if not priced:
            continue
        enforced, per_call, model = max(priced)

        floor += calls * per_call
        static += calls * enforced
        per_node[node.id] = NodeCost(
            calls=calls, usd=round(calls * enforced, 10), model=model
        )

    return BudgetEstimate(
        static_cost_usd=static,
        floor_cost_usd=floor,
        modelled_calls=calls_total,
        billable_nodes=billable,
        escalation_nodes=escalation,
        cycles=len(back_edges(document)),
        unpriced_models=tuple(unpriced),
        per_node=per_node,
    )


def static_cost_usd(document: BuilderDocument) -> float:
    """The enforced figure alone, for callers that want only the number."""

    return estimate_budget(document).static_cost_usd


def budget_problems(
    document: BuilderDocument, *, ceiling_usd: float | None = None
) -> list[Problem]:
    """Whether this graph may be published at all, on price.

    `ceiling_usd` defaults to MAX_RUN_COST_USD and is a parameter so admission
    can ask the same question against a lower per-deployment cap without this
    module reading the environment twice.

    A ceiling of 0 means DISABLED, which is the spelling MAX_RUN_COST_USD
    already uses and the one an operator who wants no brake has to type
    deliberately. An unpriced model is still refused in that case: "we cannot
    price this" is not the same statement as "we are not enforcing a price".
    """

    estimate = estimate_budget(document)
    problems: list[Problem] = []

    if estimate.unpriced_models:
        problems.append(
            Problem(
                code=BUDGET_UNPRICED_MODEL,
                severity="error",
                message=(
                    "this graph cannot be priced: "
                    f"{', '.join(estimate.unpriced_models)} has no entry in PRICES, so every "
                    "call it makes would contribute $0.00 to a total that is supposed to bound "
                    "spend. Add the model to data/models.json in the same commit that names it"
                ),
            )
        )

    ceiling = MAX_RUN_COST_USD if ceiling_usd is None else ceiling_usd
    if ceiling <= 0:
        return problems

    required = estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN
    if required > ceiling:
        problems.append(
            Problem(
                code=BUDGET_OVER_CEILING,
                severity="error",
                message=(
                    f"this graph's worst case prices at ${estimate.static_cost_usd:.2f} over "
                    f"{estimate.modelled_calls} model calls, and ${required:.2f} with the "
                    f"{GRAPH_STATIC_BUDGET_MARGIN}x margin, against a per-run ceiling of "
                    f"${ceiling:.2f}. Remove a node that calls a model, move one to the cheap "
                    "tier, take a node off a cycle, or lower a retry ceiling"
                ),
            )
        )
    return problems
