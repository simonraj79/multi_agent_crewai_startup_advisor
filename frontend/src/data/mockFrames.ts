import type { FrameData, FrameKind, FrameLevel } from '../types/studio'

export interface MockScriptStep {
  delayMs: number
  frame: FrameData
}

export function buildMockSegments(runId: string): MockScriptStep[][] {
  let seq = 0
  const startedAt = Date.now()
  const make = (
    kind: FrameKind,
    eventType: string,
    message: string,
    nodeId?: string,
    details: Record<string, unknown> = {},
    level: FrameLevel = 'INFO',
    durationMs?: number,
    delayMs = 460,
  ): MockScriptStep => {
    seq += 1
    return {
      delayMs,
      frame: {
        v: 1,
        seq,
        run_id: runId,
        ts: new Date(startedAt + seq * 720).toISOString(),
        kind,
        event_type: eventType,
        level,
        node_id: nodeId,
        message,
        details,
        duration_ms: durationMs,
      },
    }
  }

  return [
    [
      make('run_state', 'RUN_QUEUED', 'Run accepted and queued.', undefined, { status: 'queued' }, 'INFO', undefined, 180),
      make('run_state', 'RUN_STARTED', 'Validator run started.', undefined, { status: 'running' }, 'INFO', undefined, 380),
      make('node_state', 'NODE_START', 'Parsing the idea into testable claims.', 'scoper'),
      make('llm', 'LLM_CALL_STARTED', 'Scoper is structuring the validation scope.', 'scoper', { stage: 'before', call_id: 'scope-llm', model: 'escalation' }),
      make('token', 'TOKEN_USAGE', 'Scope model usage recorded.', 'scoper', { call_id: 'scope-llm', usage: { prompt_tokens: 682, completion_tokens: 241, total_tokens: 923, cost_usd: 0.0048 } }),
      make('llm', 'LLM_CALL_COMPLETED', 'Three independent research questions are ready.', 'scoper', { stage: 'after', call_id: 'scope-llm', model: 'escalation' }, 'INFO', 2840),
      make('node_state', 'NODE_END', 'Scope prepared for operator review.', 'scoper', {}, 'INFO', 3310),
      make('edge_taken', 'EDGE_TRAVERSED', 'Scope moved to operator review.', undefined, { from: 'scoper', to: 'scope_gate' }),
      make('node_state', 'NODE_WAITING', 'Waiting for scope confirmation.', 'scope_gate'),
      make('gate_open', 'GATE_OPEN', 'Confirm the parsed scope before research begins.', 'scope_gate', {
        gate_id: 'scope-confirmation',
        title: 'Confirm scope',
        summary: 'Check the market, primary user, and technical claim before the three research branches begin.',
        editable: true,
        expires_at: new Date(startedAt + 10 * 60 * 1000).toISOString(),
        fields: {
          market: 'Design-to-code tooling',
          audience: 'Frontend product teams using Figma and React',
          technology: 'Figma-to-production React generation',
        },
        options: [
          { id: 'scope_revise', label: 'Revise', emphasis: 'danger' },
          { id: 'scope_ok', label: 'Approve scope', emphasis: 'primary' },
        ],
      }, 'WARNING', undefined, 520),
    ],
    [
      make('gate_closed', 'GATE_CLOSED', 'Scope approved. Research fan-out released.', 'scope_gate', { gate_id: 'scope-confirmation', outcome: 'scope_ok' }, 'INFO', undefined, 220),
      make('node_state', 'NODE_END', 'Scope gate approved.', 'scope_gate'),
      make('edge_taken', 'EDGE_TRAVERSED', 'Market branch released.', undefined, { from: 'scope_gate', to: 'market_analyst' }, 'INFO', undefined, 140),
      make('edge_taken', 'EDGE_TRAVERSED', 'Demand branch released.', undefined, { from: 'scope_gate', to: 'sentiment_analyst' }, 'INFO', undefined, 140),
      make('edge_taken', 'EDGE_TRAVERSED', 'Feasibility branch released.', undefined, { from: 'scope_gate', to: 'feasibility_analyst' }, 'INFO', undefined, 140),
      make('node_state', 'NODE_START', 'Mapping category, segments, and pricing.', 'market_analyst'),
      make('node_state', 'NODE_START', 'Searching for pain and maintained workarounds.', 'sentiment_analyst', {}, 'INFO', undefined, 120),
      make('node_state', 'NODE_START', 'Checking implementation paths and incumbents.', 'feasibility_analyst', {}, 'INFO', undefined, 120),
      make('tool', 'TOOL_CALL_STARTED', 'firecrawl.search · design-to-code market', 'market_analyst', { stage: 'before', tool: 'firecrawl.search' }),
      make('tool', 'TOOL_CALL_STARTED', 'hn.search · Figma handoff pain', 'sentiment_analyst', { stage: 'before', tool: 'hn.search' }, 'INFO', undefined, 160),
      make('tool', 'TOOL_CALL_STARTED', 'github.search_repositories · figma react', 'feasibility_analyst', { stage: 'before', tool: 'github.search_repositories' }, 'INFO', undefined, 160),
      make('tool', 'TOOL_CALL_COMPLETED', '12 market sources retained after dedupe.', 'market_analyst', { stage: 'after', tool: 'firecrawl.search', from_cache: false }, 'INFO', 4160, 780),
      make('tool', 'TOOL_CALL_COMPLETED', '7 relevant threads classified; 2 are weak.', 'sentiment_analyst', { stage: 'after', tool: 'hn.search', from_cache: false }, 'WARNING', 3290, 420),
      make('tool', 'TOOL_CALL_COMPLETED', '18 repositories checked for maintenance and licensing.', 'feasibility_analyst', { stage: 'after', tool: 'github.search_repositories', from_cache: false }, 'INFO', 3670, 420),
      make('token', 'TOKEN_USAGE', 'Parallel analyst usage recorded.', undefined, { usage: { promptTokens: 4210, completionTokens: 1684, totalTokens: 5894, costUsd: 0.0061 } }),
      make('node_state', 'NODE_END', 'Market landscape complete.', 'market_analyst', {}, 'INFO', 6120),
      make('node_state', 'NODE_END', 'Demand evidence complete with two thin signals.', 'sentiment_analyst', {}, 'WARNING', 5840, 120),
      make('node_state', 'NODE_END', 'Technical feasibility assessment complete.', 'feasibility_analyst', {}, 'INFO', 5930, 120),
      make('edge_taken', 'EDGE_TRAVERSED', 'Market evidence joined synthesis.', undefined, { from: 'market_analyst', to: 'synthesist' }),
      make('edge_taken', 'EDGE_TRAVERSED', 'Demand evidence joined synthesis.', undefined, { from: 'sentiment_analyst', to: 'synthesist' }, 'INFO', undefined, 130),
      make('edge_taken', 'EDGE_TRAVERSED', 'Feasibility evidence joined synthesis.', undefined, { from: 'feasibility_analyst', to: 'synthesist' }, 'INFO', undefined, 130),
      make('node_state', 'NODE_START', 'Applying the deterministic five-dimension rubric.', 'synthesist'),
      make('llm', 'LLM_CALL_STARTED', 'Synthesist is reconciling evidence and score anchors.', 'synthesist', { stage: 'before', call_id: 'synthesis-llm', model: 'escalation' }),
      make('token', 'TOKEN_USAGE', 'Synthesis usage recorded.', 'synthesist', { call_id: 'synthesis-llm', usage: { prompt_tokens: 3028, completion_tokens: 812, total_tokens: 3840, cost_usd: 0.0126 } }),
      make('llm', 'LLM_CALL_COMPLETED', 'Draft verdict: NEEDS_WORK · confidence 0.62.', 'synthesist', { stage: 'after', call_id: 'synthesis-llm', model: 'escalation' }, 'INFO', 4210),
      make('node_state', 'NODE_END', 'Rubric scored and confidence separated.', 'synthesist', {}, 'INFO', 4680),
      make('edge_taken', 'EDGE_TRAVERSED', 'Draft verdict moved to operator review.', undefined, { from: 'synthesist', to: 'verdict_gate' }),
      make('node_state', 'NODE_WAITING', 'Waiting for verdict review.', 'verdict_gate'),
      make('metrics', 'METRICS_UPDATED', 'Run metrics updated.', undefined, { elapsed_ms: 18420, call_count: 5 }),
      make('gate_open', 'GATE_OPEN', 'Review the scored verdict before report generation.', 'verdict_gate', {
        gate_id: 'verdict-review',
        title: 'Review verdict',
        summary: 'Demand evidence is the thinnest dimension. The report will preserve that uncertainty.',
        verdict: 'NEEDS_WORK',
        confidence: 0.62,
        editable: false,
        expires_at: new Date(startedAt + 20 * 60 * 1000).toISOString(),
        options: [
          { id: 'verdict_revise', label: 'Request revision', emphasis: 'danger' },
          { id: 'verdict_ok', label: 'Accept verdict', emphasis: 'primary' },
        ],
      }, 'WARNING'),
    ],
    [
      make('gate_closed', 'GATE_CLOSED', 'Verdict accepted. Reporter released.', 'verdict_gate', { gate_id: 'verdict-review', outcome: 'verdict_ok' }, 'INFO', undefined, 220),
      make('node_state', 'NODE_END', 'Verdict gate approved.', 'verdict_gate'),
      make('edge_taken', 'EDGE_TRAVERSED', 'Accepted verdict moved to report generation.', undefined, { from: 'verdict_gate', to: 'reporter' }),
      make('node_state', 'NODE_START', 'Writing the sourced one-page validation brief.', 'reporter'),
      make('llm', 'LLM_CALL_STARTED', 'Reporter is composing the brief and attribution table.', 'reporter', { stage: 'before', call_id: 'report-llm', model: 'escalation' }),
      make('token', 'TOKEN_USAGE', 'Reporter usage recorded.', 'reporter', { call_id: 'report-llm', usage: { prompt_tokens: 2489, completion_tokens: 1054, total_tokens: 3543, cost_usd: 0.0157 } }),
      make('llm', 'LLM_CALL_COMPLETED', 'Brief passed mechanics and source attribution checks.', 'reporter', { stage: 'after', call_id: 'report-llm', model: 'escalation' }, 'INFO', 3890),
      make('node_state', 'NODE_END', 'Validation brief written.', 'reporter', {}, 'INFO', 4290),
      make('edge_taken', 'EDGE_TRAVERSED', 'Validated report published.', undefined, { from: 'reporter', to: 'final' }),
      make('node_state', 'NODE_END', 'output/validation.md is ready.', 'final'),
      make('metrics', 'METRICS_UPDATED', 'Final usage and cost calculated.', undefined, { elapsed_ms: 27430, call_count: 7 }),
      make('run_state', 'RUN_COMPLETED', 'Run completed with a NEEDS_WORK verdict.', undefined, { status: 'completed' }, 'INFO', 27430),
    ],
  ]
}