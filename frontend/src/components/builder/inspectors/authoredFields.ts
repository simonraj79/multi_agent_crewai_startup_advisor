/**
 * Which control sits in which tier - 04 D2's table, as data.
 *
 * ONE DECLARATION, THREE READERS, and that is the whole reason this is a module
 * rather than three arrays inside a form:
 *
 *   1. `AuthoredAgentForm` renders the regions in this order.
 *   2. `TierRegion`'s `count` is the length of one of these, so the "N expert
 *      settings hidden" line cannot drift from what pressing "show" reveals.
 *   3. `InspectorRail`'s `INSPECTOR_FIELDS` is their union, which is what stops
 *      a problem anchored to a control this form DOES render from being pinned
 *      to the top strip as if no control existed for it.
 *
 * The third is the one that fails silently. `unplacedForNode` takes the fields
 * the open form renders; hand it a stale list and a real problem appears twice,
 * or in the wrong place, and nothing anywhere says so.
 *
 * THE NAMES ARE DOCUMENT PATHS, not control ids, because that is what
 * `FIELD_CODES` and C8's `field` both spell: `task.description`,
 * `llm.response_format`, `retry.fallback_model`. `data-field` on the row
 * carries the same string, which is what makes `InspectorRail.focusField`
 * a DOM query rather than a chain of refs through `<component :is>`.
 *
 * THE ARITHMETIC, stated once so nobody has to rederive it. FD5's authored
 * agent is 41 leaf controls. The 00 S9 deprecation ruling cuts two
 * (`multimodal`, `function_calling_llm`), replaces two (`reasoning`,
 * `max_reasoning_attempts`) with five (`planning` plus `planning_config`'s
 * four), and leaves the rest alone: 41 − 2 − 2 + 5 = **42**. `attachments` is
 * not one of them - it is a read-out over `attach` edges, not a field - which
 * is why it is listed under Essentials for ANCHORING purposes and excluded
 * from the count that is printed.
 */

/**
 * Always open. The five that matter, plus the model and the tier preset that
 * sets it, plus the read-out of what is wired to this node.
 *
 * `tier` is here because the preset chips write it, and a problem anchored to
 * `tier` - `escalation-count`, `billable-count` - has to land on the row that
 * shows it. `attachments` is here for the same reason and is not a field.
 */
export const ESSENTIAL_FIELDS = [
  'role',
  'goal',
  'backstory',
  'task.description',
  'task.expected_output',
  'tier',
  'llm.model',
  'attachments',
] as const

/**
 * Closed by default, remembered per node kind. Twenty-one controls.
 *
 * The rule of thumb that put each one here: an author who has not asked the
 * question does not need the control, and every one of these answers a question
 * you only have once the node is doing roughly the right thing. `max_iter` and
 * `guardrail_max_retries` sit here rather than in Essentials even though they
 * dominate the price, because the budget meter is what tells an author to come
 * looking - a number is a better prompt than a control.
 */
export const ADVANCED_FIELDS = [
  'task.output_schema',
  'task.markdown',
  'task.async_execution',
  'llm.temperature',
  'llm.top_p',
  'llm.max_tokens',
  'llm.timeout',
  'llm.response_format',
  'max_iter',
  'max_rpm',
  'max_execution_time',
  'allow_delegation',
  'memory',
  'cache',
  'respect_context_window',
  'guardrail_max_retries',
  'retry.max_retries',
  'retry.backoff_seconds',
  'retry.fallback_model',
  'on_error',
  'prompt_inputs',
] as const

/**
 * Behind the global switch. Fourteen controls, four of which appear only while
 * `planning` is on.
 *
 * The four conditional ones are LAST in the array on purpose:
 * `AuthoredAgentForm.expertCount` subtracts four when planning is off, and it
 * can only do that honestly because they are a contiguous tail that nothing
 * else counts on being present.
 */
export const EXPERT_FIELDS = [
  'llm.frequency_penalty',
  'llm.presence_penalty',
  'llm.stop',
  'llm.seed',
  'llm.reasoning_effort',
  'system_template',
  'prompt_template',
  'response_template',
  'tool_failure_policy',
  'planning',
  'planning_config.reasoning_effort',
  'planning_config.max_attempts',
  'planning_config.max_steps',
  'planning_config.max_replans',
] as const

/** Every control an authored agent's inspector renders. `INSPECTOR_FIELDS`' agent row. */
export const AUTHORED_AGENT_FIELDS: readonly string[] = [
  ...ESSENTIAL_FIELDS,
  ...ADVANCED_FIELDS,
  ...EXPERT_FIELDS,
]

/**
 * The authored crew's fifteen, tiered - 04 D2's crew paragraph plus the S9
 * ruling's fifteenth field.
 *
 * `verbose` IS the fifteenth (ruled 2026-09-04) and it is placed in **Advanced**
 * rather than Essentials, which is a departure from the gauntlet's own Crew
 * Essentials line and is deliberate. 04 D2's Essentials list for a crew is
 * explicit and complete - `process`, the member list, and one of the two
 * managers - and 00's own "fields the gauntlet names that no plan places" table
 * gives the reason `verbose` was dropped in the first place: it is console
 * noise, and the run console reads frames instead. Rendering it honours the
 * ruling; rendering it in Advanced honours the tiering the same plan wrote.
 *
 * `max_iter` and `guardrail_max_retries` are here too. The crew paragraph names
 * neither, but `AuthoredCrewConfig` inherits both from `_BillableConfig`, so
 * they are stored fields with no control - which is the one state a form must
 * never leave a field in, because it round-trips a value the author cannot see.
 */
export const CREW_ESSENTIAL_FIELDS = [
  'tier',
  'process',
  'members',
  'task_order',
  'manager_agent',
  'manager_llm.model',
] as const

export const CREW_ADVANCED_FIELDS = [
  'memory',
  'cache',
  'max_rpm',
  'verbose',
  'planning',
  'planning_llm.model',
  'max_iter',
  'guardrail_max_retries',
  'retry.max_retries',
  'retry.backoff_seconds',
  'retry.fallback_model',
  'on_error',
  'prompt_inputs',
] as const

export const AUTHORED_CREW_FIELDS: readonly string[] = [
  ...CREW_ESSENTIAL_FIELDS,
  ...CREW_ADVANCED_FIELDS,
]
