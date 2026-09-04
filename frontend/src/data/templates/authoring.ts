import { edgeId, nodeId } from '../../types/builder'
import { roleToken } from './modelRoles'
import type { ModelRole } from './modelRoles'
import type {
  BuilderEdge,
  BuilderNode,
  GateConfig,
  InputConfig,
  JsonScalar,
  LlmConfig,
  NodeId,
  OutputConfig,
  RetryConfig,
  RouterBranch,
  RouterConfig,
  ScalarType,
  TaskConfig,
  ToolConfig,
  TransformConfig,
  TransformOp,
} from '../../types/builder'

/**
 * The node and edge constructors the four pattern templates are written with.
 *
 * WHY THESE EXIST AT ALL, given that `builderTemplates.ts` writes its two older
 * documents as plain literals. An AUTHORED agent has twenty-two config fields
 * and `BuilderModel` is `extra="forbid"` on the other side, so every one of
 * them has to be present and correctly spelled; four templates written that way
 * would be four hundred lines in which the interesting three - the role, the
 * task and the model - are invisible. These helpers carry the defaults so a
 * template reads as the graph it is.
 *
 * They are DEFAULTS, not policy. Every value below is either the schema's own
 * default (`document.py`) or the neutral answer for a field the schema leaves
 * optional; nothing here decides anything a template could not decide for
 * itself, and every template that wants a different answer passes one.
 *
 * `${state.out__x}` IS SPELLED OUT rather than generated from a node object,
 * because it is the one piece of syntax these templates exist to teach. An
 * author reading `reflectionLoop.ts` should see the same string they will type
 * into the inspector.
 */

/** `${state.out__<node>}` - the previous step's output, as a prompt input. */
export const out = (node: string): string => `\${state.out__${node}}`

/** `${state.<field>}` - an input node's own seeded value. */
export const stateRef = (field: string): string => `\${state.${field}}`

/** The compiled state key a router branch compares against a node's output. */
export const outKey = (node: string): NodeId => nodeId(`out__${node}`)

/** One flow edge. `'in'` is the only target port a step accepts. */
export function flowEdge(
  id: string,
  source: string,
  target: string,
  port = 'out',
): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(source),
    source_port: port,
    target: nodeId(target),
    target_port: 'in',
  }
}

/**
 * One `attach` edge: a possession reaching toward the agent that holds it.
 *
 * The direction is the asymmetry `document.py` draws on purpose - an attachment
 * has one port and it is a SOURCE - so this reads tool-to-agent and never the
 * other way.
 */
export function attachEdge(id: string, tool: string, holder: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(tool),
    source_port: 'attach',
    target: nodeId(holder),
    target_port: 'attach',
  }
}

/** One `member` edge: an agent that runs inside a crew rather than beside it. */
export function memberEdge(id: string, agent: string, crew: string): BuilderEdge {
  return {
    id: edgeId(id),
    source: nodeId(agent),
    source_port: 'out',
    target: nodeId(crew),
    target_port: 'member',
  }
}

export function inputNode(
  id: string,
  label: string,
  prompt: string,
  position: { x: number; y: number },
): BuilderNode {
  const config: InputConfig = {
    field: nodeId(id),
    label: prompt,
    max_chars: 2000,
    required: true,
  }
  return { id: nodeId(id), kind: 'input', label, position, config }
}

/**
 * The human gate every one of these templates puts above its first billable node.
 *
 * NOT decoration, and not the plan's own node tables - it is what makes the
 * template launchable by somebody who is not signed in. `create_run` answers
 * **403** for a published graph that reaches a billable node before any human
 * gate unless `BUILDER_ALLOW_GATELESS_GRAPHS` is set, on the argument that
 * while nobody is signed in human inaction IS the spend cap. A synthetic
 * backend with no `AUTH_BASE_URL` resolves every caller to nobody, so a
 * gateless template is a template the E2E suite cannot launch either.
 *
 * `max_turns: 1` and no edge from `revise`: the operator may send the request
 * back once, and a gate whose revise port goes nowhere ends the run there. That
 * is the same shape `MINIMAL_GATED_AGENT` has shipped with since 2026-09-02.
 */
export function gateNode(
  id: string,
  label: string,
  message: string,
  position: { x: number; y: number },
): BuilderNode {
  const config: GateConfig = {
    message,
    editable_fields: [],
    max_turns: 1,
    expiry_seconds: 1800,
  }
  return { id: nodeId(id), kind: 'gate', label, position, config }
}

/**
 * An output node whose body comes from the edge the author drew.
 *
 * `source: null` on purpose. Until `8e24e35` an unset source compiled to
 * nothing and a run SUCCEEDED, spent money and handed back an empty body after
 * validating with zero problems; it now follows the node's incoming edge, which
 * is the behaviour a drag-and-drop author gets. Hand-typing
 * `${state.out__write}` here would still work and would stop these templates
 * exercising the default that the paid run was needed to find.
 */
export function outputNode(
  id: string,
  label: string,
  position: { x: number; y: number },
  source: string | null = null,
): BuilderNode {
  const config: OutputConfig = { body_key: 'markdown_body', source }
  return { id: nodeId(id), kind: 'output', label, position, config }
}

export function transformNode(
  id: string,
  label: string,
  op: TransformOp,
  args: Record<string, JsonScalar>,
  position: { x: number; y: number },
): BuilderNode {
  const config: TransformConfig = { op, args }
  return { id: nodeId(id), kind: 'transform', label, position, config }
}

export function routerNode(
  id: string,
  label: string,
  branches: RouterBranch[],
  position: { x: number; y: number },
): BuilderNode {
  const config: RouterConfig = { branches }
  return { id: nodeId(id), kind: 'router', label, position, config }
}

/** One declared comparison. `key` is a compiled state key, never a node id. */
export const branch = (
  label: string,
  op: RouterBranch['op'],
  key: NodeId | null = null,
  value: JsonScalar = null,
): RouterBranch => ({ label: nodeId(label), op, key, value })

export function toolNode(
  id: string,
  label: string,
  toolId: string,
  position: { x: number; y: number },
  params: Record<string, JsonScalar> = {},
): BuilderNode {
  const config: ToolConfig = { tool_id: nodeId(toolId), params }
  return { id: nodeId(id), kind: 'tool', label, position, config }
}

/**
 * An `LlmConfig` naming a ROLE rather than a model, with every other leaf at
 * the provider's own default.
 *
 * Ten explicit nulls rather than a partial object: the wire model forbids
 * extras and requires the rest, and a helper that omitted a field would produce
 * a document that validates here and 422s there.
 */
export const roleLlm = (role: ModelRole): LlmConfig => ({
  model: roleToken(role),
  temperature: null,
  top_p: null,
  max_tokens: null,
  timeout: null,
  response_format: null,
  frequency_penalty: null,
  presence_penalty: null,
  stop: [],
  seed: null,
  reasoning_effort: null,
})

const NO_RETRY: RetryConfig = { max_retries: 0, backoff_seconds: 0, fallback_model: null }

interface AuthoredAgentSpec {
  readonly id: string
  readonly label: string
  readonly position: { x: number; y: number }
  readonly role: string
  readonly goal: string
  readonly backstory: string
  readonly description: string
  readonly expected: string
  readonly model: ModelRole
  readonly tier?: 'cheap' | 'escalation'
  readonly maxIter?: number
  readonly promptInputs?: Record<string, JsonScalar>
  readonly outputSchema?: Record<string, ScalarType> | null
  readonly markdown?: boolean
}

/**
 * One authored agent: a role, a goal, a backstory, one task and one model.
 *
 * `tier` defaults from the model role rather than being asked for twice.
 * It is a DECLARATION the document is priced and bounded on - `MAX_ESCALATION_NODES`
 * counts the word - so a node on the escalation model that declared `cheap`
 * would be priced at the wrong tier by every count except the money, which
 * `budget.py` takes from `llm.model` since plan 05. Keeping the two in step
 * here means a template cannot ship that disagreement.
 */
export function authoredAgent(spec: AuthoredAgentSpec): BuilderNode {
  const task: TaskConfig = {
    description: spec.description,
    expected_output: spec.expected,
    output_schema: spec.outputSchema ?? null,
    markdown: spec.markdown ?? false,
    async_execution: false,
  }
  return {
    id: nodeId(spec.id),
    kind: 'agent',
    label: spec.label,
    position: spec.position,
    config: {
      tier: spec.tier ?? (spec.model === 'escalation' ? 'escalation' : 'cheap'),
      max_iter: spec.maxIter ?? 2,
      guardrail_max_retries: 2,
      prompt_inputs: spec.promptInputs ?? {},
      role: spec.role,
      goal: spec.goal,
      backstory: spec.backstory,
      task,
      llm: roleLlm(spec.model),
      max_rpm: null,
      max_execution_time: null,
      allow_delegation: false,
      memory: false,
      cache: true,
      respect_context_window: true,
      retry: NO_RETRY,
      system_template: null,
      prompt_template: null,
      response_template: null,
      tool_failure_policy: null,
      planning: false,
      planning_config: null,
    },
  }
}

interface AuthoredCrewSpec {
  readonly id: string
  readonly label: string
  readonly position: { x: number; y: number }
  readonly process: 'sequential' | 'hierarchical'
  readonly taskOrder: readonly string[]
  readonly managerRole?: ModelRole
  readonly tier: 'cheap' | 'escalation'
  readonly promptInputs?: Record<string, JsonScalar>
}

/**
 * One authored crew: a process, an ordered member list and a manager.
 *
 * The MEMBERSHIP is not here - it is the set of `member` edges arriving at this
 * node - and `task_order` is only the order those members' tasks run in.
 * `manager_llm` is required by `AuthoredCrewConfig._validate_manager` for a
 * hierarchical process and REFUSED for a sequential one, which is CrewAI's own
 * rule (`crew.py:729`) checked before a canvas can publish it rather than after
 * every upstream node has billed.
 */
export function authoredCrew(spec: AuthoredCrewSpec): BuilderNode {
  return {
    id: nodeId(spec.id),
    kind: 'crew',
    label: spec.label,
    position: spec.position,
    config: {
      tier: spec.tier,
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: spec.promptInputs ?? {},
      process: spec.process,
      task_order: spec.taskOrder.map((id) => nodeId(id)),
      manager_llm: spec.managerRole ? roleLlm(spec.managerRole) : null,
      manager_agent: null,
      memory: false,
      cache: true,
      max_rpm: null,
      planning: false,
      planning_llm: null,
      retry: NO_RETRY,
      verbose: false,
    },
  }
}
