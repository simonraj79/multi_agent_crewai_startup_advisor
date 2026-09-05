import { describe, expect, it } from 'vitest'
import {
  HUMANISE_PRESERVED_TOKENS,
  humaniseCode,
  humaniseTask,
  humaniseTool,
} from '../src/utils/humanise'

/**
 * The contract is one sentence: whatever comes in, what goes out is words.
 *
 * The interesting half is the UNKNOWN input. A lookup table can render the
 * eight floor codes that exist today; what T1.4 asks for is that a code nobody
 * has written yet still reaches the operator as English. So the block that
 * matters most here is the fallback one, not the recognised one.
 */
describe('humaniseCode', () => {
  it('renders SNAKE_CASE as a sentence', () => {
    expect(humaniseCode('INSUFFICIENT_EVIDENCE')).toBe('Insufficient evidence')
    expect(humaniseCode('NEEDS_WORK')).toBe('Needs work')
    expect(humaniseCode('VALIDATE')).toBe('Validate')
  })

  it('strips a namespace only when the caller names it', () => {
    expect(humaniseCode('FLOOR_NO_MARKET')).toBe('Floor no market')
    expect(humaniseCode('FLOOR_NO_MARKET', { stripPrefix: 'FLOOR_' })).toBe('No market')
    // With or without the trailing separator, and case-insensitively: all
    // three spellings mean the same thing to a caller.
    expect(humaniseCode('FLOOR_NO_MARKET', { stripPrefix: 'FLOOR' })).toBe('No market')
    expect(humaniseCode('FLOOR_NO_MARKET', { stripPrefix: 'floor_' })).toBe('No market')
    expect(humaniseCode('ERR_TIMEOUT', { stripPrefix: 'ERR_' })).toBe('Timeout')
  })

  it('will not eat a prefix that is only a prefix of a word', () => {
    // `FLOOR_` must not turn FLOORING_COLLAPSED into "Ing collapsed".
    expect(humaniseCode('FLOORING_COLLAPSED', { stripPrefix: 'FLOOR_' })).toBe(
      'Flooring collapsed',
    )
  })

  it('keeps something to render when the code IS the prefix', () => {
    expect(humaniseCode('FLOOR', { stripPrefix: 'FLOOR_' })).toBe('Floor')
  })

  it('renders snake_case identifiers', () => {
    expect(humaniseCode('market_task')).toBe('Market task')
    expect(humaniseCode('research_market_landscape')).toBe('Research market landscape')
    expect(humaniseCode('scope_idea')).toBe('Scope idea')
  })

  it('renders camelCase and PascalCase', () => {
    expect(humaniseCode('competitiveRoom')).toBe('Competitive room')
    expect(humaniseCode('MarketFindings')).toBe('Market findings')
    expect(humaniseCode('marketTask_v2')).toBe('Market task v2')
  })

  it('renders kebab-case and dotted identifiers', () => {
    expect(humaniseCode('library-missing-prompt-input')).toBe('Library missing prompt input')
    expect(humaniseCode('tools.market_research')).toBe('Tools market research')
  })

  it('leaves prose alone, punctuation included', () => {
    expect(humaniseCode('Insufficient evidence')).toBe('Insufficient evidence')
    expect(humaniseCode('No market')).toBe('No market')
    expect(humaniseCode('The market has no nameable buyer.')).toBe(
      'The market has no nameable buyer.',
    )
  })

  it('returns an empty string for empty and whitespace input', () => {
    expect(humaniseCode('')).toBe('')
    expect(humaniseCode('   ')).toBe('')
  })

  it('preserves acronyms and brand tokens', () => {
    expect(humaniseCode('LLM_call_failed')).toBe('LLM call failed')
    expect(humaniseCode('HN_sentiment')).toBe('HN sentiment')
    expect(humaniseCode('api_key_missing')).toBe('API key missing')
    expect(humaniseCode('github_feasibility')).toBe('GitHub feasibility')
    expect(humaniseCode('openrouter_ceiling')).toBe('OpenRouter ceiling')
    expect(humaniseCode('MCP_STDIO_DISABLED')).toBe('MCP stdio disabled')
  })

  it('treats an unknown short shout as an acronym', () => {
    // Nobody registered KPI, and rendering it "Kpi" would read as a typo.
    expect(humaniseCode('KPI_missing')).toBe('KPI missing')
  })

  it('does not mistake a short English word for an acronym', () => {
    // The reason COMMON_SHORT_WORDS exists: "NO market" is worse than the code.
    expect(humaniseCode('NO_MARKET')).toBe('No market')
    expect(humaniseCode('RUN_OUT_OF_BUDGET')).toBe('Run out of budget')
    expect(humaniseCode('ALL_SET')).toBe('All set')
  })

  it('exports the allowlist it uses', () => {
    expect(HUMANISE_PRESERVED_TOKENS).toContain('LLM')
    expect(HUMANISE_PRESERVED_TOKENS).toContain('GitHub')
    expect(HUMANISE_PRESERVED_TOKENS).toContain('OpenRouter')
  })

  it('never emits a SNAKE_CASE token, for any of these inputs', () => {
    const codes = [
      'FLOOR_ALREADY_FREE',
      'FLOOR_NO_DEMAND',
      'INSUFFICIENT_EVIDENCE',
      'SOME_CODE_NOBODY_HAS_WRITTEN_YET',
      'a_very_long_identifier_with_many_parts',
      'ERR_UPSTREAM_5XX',
    ]
    for (const code of codes) {
      expect(humaniseCode(code)).not.toMatch(/\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b/)
      expect(humaniseCode(code)).not.toContain('_')
    }
  })
})

describe('humaniseTask', () => {
  it('drops a trailing task word', () => {
    expect(humaniseTask('market_task')).toBe('Market')
    expect(humaniseTask('sentiment_task')).toBe('Sentiment')
    expect(humaniseTask('reporting_task')).toBe('Reporting')
    expect(humaniseTask('verifyClaimsTask')).toBe('Verify claims')
  })

  it('drops a leading task word', () => {
    expect(humaniseTask('task_verify_claims')).toBe('Verify claims')
  })

  it('leaves a task name that does not say task', () => {
    expect(humaniseTask('write_report')).toBe('Write report')
    expect(humaniseTask('research_market_landscape')).toBe('Research market landscape')
  })

  it('keeps the word when it is the whole name', () => {
    expect(humaniseTask('task')).toBe('Task')
    expect(humaniseTask('TASK')).toBe('Task')
  })

  it('returns an empty string for empty input', () => {
    expect(humaniseTask('')).toBe('')
  })
})

describe('humaniseTool', () => {
  it('renders a snake_case tool id', () => {
    expect(humaniseTool('research_market_landscape')).toBe('Research market landscape')
    expect(humaniseTool('analyze_community_sentiment')).toBe('Analyze community sentiment')
    expect(humaniseTool('assess_technical_feasibility')).toBe('Assess technical feasibility')
  })

  it('drops a trailing tool word in either convention', () => {
    expect(humaniseTool('hn_sentiment_tool')).toBe('HN sentiment')
    expect(humaniseTool('FirecrawlScrapeWebsiteTool')).toBe('Firecrawl scrape website')
  })

  it('keeps the word when it is the whole name', () => {
    expect(humaniseTool('tool')).toBe('Tool')
  })

  it('returns an empty string for empty input', () => {
    expect(humaniseTool('')).toBe('')
  })
})
