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
    usd        += calls x compute_cost_usd(tier's model, prompt, 4,253)

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
   its own: `:nitro` routes on speed, not price, so the cheap tier's published
   rate is a floor. NITRO_PRICE_FACTOR is the interim answer, and
   `floor_cost_usd` keeps the un-inflated figure beside the enforced one so the
   two can be told apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from brief_crew.builder.bounds import Problem, billable_depths, back_edges, nodes_on_cycles
from brief_crew.builder.document import (
    AgentConfig,
    BuilderBudget,
    BuilderDocument,
    BuilderNode,
)
from brief_crew.config import (
    CHEAP_MODEL,
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

    def as_budget(self, *, compiled_at: datetime | None = None) -> BuilderBudget:
        """The block the compiler writes onto the document it priced."""

        return BuilderBudget(
            static_cost_usd=self.static_cost_usd,
            billable_nodes=self.billable_nodes,
            escalation_nodes=self.escalation_nodes,
            cycles=self.cycles,
            compiled_at=compiled_at or datetime.now(timezone.utc),
        )


def _calls_for(node: BuilderNode, *, on_cycle: bool) -> int:
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
    binds_tools = not isinstance(config, AgentConfig) or bool(config.tools)
    calls = attempts * ((getattr(config, "max_iter", 1) + 1) if binds_tools else 1)
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
    return _calls_for(node, on_cycle=node_id in nodes_on_cycles(document))


def estimate_budget(document: BuilderDocument) -> BudgetEstimate:
    """Price the whole graph at its worst case. Never raises."""

    depths = billable_depths(document)
    cyclic = nodes_on_cycles(document)

    static = 0.0
    floor = 0.0
    calls_total = 0
    billable = 0
    escalation = 0
    unpriced: list[str] = []

    for node in document.nodes:
        if not node.is_billable:
            continue
        billable += 1
        tier = node.tier or "cheap"
        if tier == "escalation":
            escalation += 1

        calls = _calls_for(node, on_cycle=node.id in cyclic)
        calls_total += calls

        model = _MODEL_BY_TIER[tier]
        prompt_tokens = (
            GRAPH_BUDGET_SEED_PROMPT_TOKENS
            + depths.get(node.id, 0) * GRAPH_BUDGET_CALL_COMPLETION_TOKENS
        )
        per_call = compute_cost_usd(model, prompt_tokens, GRAPH_BUDGET_CALL_COMPLETION_TOKENS)
        if per_call is None:
            if model not in unpriced:
                unpriced.append(model)
            continue

        floor += calls * per_call
        static += calls * per_call * (NITRO_PRICE_FACTOR if tier == "cheap" else 1.0)

    return BudgetEstimate(
        static_cost_usd=static,
        floor_cost_usd=floor,
        modelled_calls=calls_total,
        billable_nodes=billable,
        escalation_nodes=escalation,
        cycles=len(back_edges(document)),
        unpriced_models=tuple(unpriced),
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
                    "spend. Add the price in the same commit as the model"
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
