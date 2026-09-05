/**
 * Turn an internal identifier into words a person can read.
 *
 * The run shell renders strings the backend chose for machines: floor codes
 * (`FLOOR_NO_MARKET`), CrewAI task names (`market_task`), tool ids
 * (`research_market_landscape`), verdict labels (`NEEDS_WORK`) and the odd
 * camelCase key. None of those is prose, and every surface that showed one raw
 * was leaking a code at the operator - which is the defect T1.3 and T1.4 of
 * `docs/run-shell/DEFINITION-OF-DONE.md` exist to close.
 *
 * The rules are mechanical rather than a lookup table, because a table cannot
 * answer for a code that did not exist when it was written. An unknown floor
 * code, an unknown dimension key and a task name from a flow somebody invents
 * next week all come out as sentence-cased words rather than as SNAKE_CASE.
 * That is the whole contract: never a code, even when the code is
 * unrecognised.
 *
 * Pure, dependency-free and side-effect-free by construction - it is imported
 * by the verdict display, the trace interpretation layer and the character
 * system, so anything it pulled in would be pulled into all three.
 */

/**
 * Tokens whose casing is theirs, not ours.
 *
 * Two shapes, and they are different problems. An acronym (`LLM`, `HN`) is
 * upper-cased for a reason a sentence-case pass cannot know, so lower-casing it
 * produces "Llm", which reads as a typo. A brand (`GitHub`, `OpenRouter`)
 * carries an internal capital that no casing rule of ours would ever restore
 * once it is gone.
 *
 * Exported so a caller can read the list rather than discover it by being
 * surprised, and so a spec can assert against it. Membership is matched
 * case-insensitively, and the SPELLING written here is the one emitted.
 */
export const HUMANISE_PRESERVED_TOKENS: readonly string[] = [
  // Acronyms.
  'AI',
  'API',
  'CSV',
  'HN',
  'HTML',
  'HTTP',
  'ID',
  'JSON',
  'LLM',
  'MCP',
  'NDJSON',
  'PDF',
  'SQL',
  'UI',
  'URL',
  'UX',
  'ZIP',
  // Brands, whose internal capitals no casing rule would restore.
  'CrewAI',
  'GitHub',
  'JavaScript',
  'OpenAI',
  'OpenRouter',
  'PostgreSQL',
  'PyPI',
  'TypeScript',
  'YouTube',
  'npm',
]

/** Lower-cased spelling -> the spelling emitted. Built once. */
const PRESERVED_BY_LOWER = new Map<string, string>(
  HUMANISE_PRESERVED_TOKENS.map((token) => [token.toLowerCase(), token]),
)

/**
 * Short words that arrive SHOUTED and are words, not acronyms.
 *
 * The generous rule below keeps an unrecognised all-caps run of two or three
 * letters as an acronym, on the grounds that `KPI` is far more likely than a
 * word somebody typed angrily. `FLOOR_NO_MARKET` is the counter-example that
 * makes the exception necessary: without this set it renders "NO market",
 * which is worse than the code it replaced. Every entry here is an ordinary
 * English word that also happens to be short.
 */
const COMMON_SHORT_WORDS = new Set([
  'ALL',
  'AND',
  'ANY',
  'ARE',
  'AS',
  'AT',
  'BAD',
  'BE',
  'BUT',
  'BY',
  'CAN',
  'DID',
  'DO',
  'END',
  'FEW',
  'FOR',
  'GET',
  'GOT',
  'HAD',
  'HAS',
  'IF',
  'IN',
  'IS',
  'IT',
  'LOW',
  'MAY',
  'NEW',
  'NO',
  'NOT',
  'OF',
  'OFF',
  'OLD',
  'ON',
  'ONE',
  'OR',
  'OUT',
  'RAN',
  'RUN',
  'SET',
  'SO',
  'THE',
  'TO',
  'TOO',
  'TOP',
  'TWO',
  'UP',
  'USE',
  'WAS',
  'WHY',
  'YES',
  'YET',
])

export interface HumaniseOptions {
  /**
   * A leading namespace to drop, e.g. `FLOOR_` on `FLOOR_NO_MARKET`.
   *
   * Opt-in and named, never guessed, and nothing is stripped by default. A
   * default that removed "everything before the first underscore" would turn
   * `market_task` into "Task" and `scope_idea` into "Idea", which is worse
   * than the code it replaced. The caller knows which namespace it is
   * rendering; this module does not.
   *
   * Matched case-insensitively, with or without its trailing separator, only
   * at the start, and only on a real word boundary - `FLOOR_` does not eat the
   * front of `FLOORING_COLLAPSED`.
   */
  stripPrefix?: string
}

/** Separators inside an identifier that are always word breaks. */
const SEPARATORS = /[_\-:/\s]+/
/** A boundary character, for the prefix check. */
const BOUNDARY = /^[_\-.:/\s]/

/**
 * Split an identifier into its words, whatever convention it was written in.
 *
 * `SNAKE_CASE`, `kebab-case`, `dotted.path`, `camelCase` and `PascalCase` all
 * arrive here, sometimes mixed (`marketTask_v2`). Two rules earn their keep:
 *
 * - A camel boundary is only a boundary when the chunk is not already an
 *   all-caps run, or `NEEDS_WORK` would split into N, E, E, D, S.
 * - A dot separates words only in a string with no whitespace in it. A string
 *   with a space is prose, and in prose a dot is a full stop: splitting on it
 *   would silently delete the punctuation from an already-readable sentence,
 *   which is the one thing this function must never do.
 */
function words(value: string): string[] {
  const looksLikeIdentifier = !/\s/.test(value)
  const source = looksLikeIdentifier ? value.replace(/\./g, '_') : value
  const out: string[] = []
  for (const chunk of source.split(SEPARATORS)) {
    if (!chunk) continue
    if (chunk === chunk.toUpperCase()) {
      // An all-caps chunk has no camel boundaries to find.
      out.push(chunk)
      continue
    }
    // `HTTPServer` -> `HTTP`, `Server`; `camelCase` -> `camel`, `Case`.
    const parts = chunk
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
      .split(' ')
    for (const part of parts) if (part) out.push(part)
  }
  return out
}

/** True when this word keeps its own spelling rather than taking ours. */
function isPreserved(word: string): boolean {
  if (PRESERVED_BY_LOWER.has(word.toLowerCase())) return true
  const bare = word.replace(/[^A-Za-z0-9]/g, '')
  if (!bare) return false
  return (
    bare.length >= 2 &&
    bare.length <= 3 &&
    bare === bare.toUpperCase() &&
    /^[A-Z]+$/.test(bare) &&
    !COMMON_SHORT_WORDS.has(bare)
  )
}

/** One word, cased for the middle of a sentence. */
function caseWord(word: string): string {
  const preserved = PRESERVED_BY_LOWER.get(word.toLowerCase())
  if (preserved) return preserved
  if (isPreserved(word)) return word
  return word.toLowerCase()
}

/** Drop `stripPrefix` from the front of `value`, if it is there. */
function stripNamespace(value: string, prefix: string | undefined): string {
  if (!prefix) return value
  const cleaned = prefix.replace(/[_\-.:/\s]+$/, '')
  if (!cleaned) return value
  if (!value.toLowerCase().startsWith(cleaned.toLowerCase())) return value
  const rest = value.slice(cleaned.length)
  if (rest && !BOUNDARY.test(rest)) return value
  const stripped = rest.replace(/^[_\-.:/\s]+/, '')
  // Stripping everything leaves nothing to render, so keep the original.
  return stripped || value
}

/**
 * `FLOOR_NO_MARKET` -> "No market" (with `{ stripPrefix: 'FLOOR_' }`),
 * `INSUFFICIENT_EVIDENCE` -> "Insufficient evidence",
 * `competitiveRoom` -> "Competitive room", already-prose left alone.
 */
export function humaniseCode(code: string, options: HumaniseOptions = {}): string {
  if (typeof code !== 'string') return ''
  const trimmed = code.trim()
  if (!trimmed) return ''
  const stripped = stripNamespace(trimmed, options.stripPrefix)
  const parts = words(stripped)
  if (parts.length === 0) return ''
  const cased = parts.map(caseWord)
  // Sentence case: the first word carries the capital, unless it is a token
  // whose own spelling was agreed above.
  if (!isPreserved(parts[0])) {
    cased[0] = cased[0].charAt(0).toUpperCase() + cased[0].slice(1)
  }
  return cased.join(' ')
}

/** Words a task identifier wears and a person does not read. */
const TASK_NOISE = new Set(['task', 'tasks'])
/** Words a tool identifier wears and a person does not read. */
const TOOL_NOISE = new Set(['tool', 'tools'])

/**
 * Humanise `name` after dropping the leading and trailing noise words in
 * `noise`, but only while something is left to render.
 */
function humaniseWithout(
  name: string,
  noise: ReadonlySet<string>,
  options: HumaniseOptions,
): string {
  if (typeof name !== 'string') return ''
  const trimmed = name.trim()
  if (!trimmed) return ''
  const stripped = stripNamespace(trimmed, options.stripPrefix)
  const parts = words(stripped)
  // One word only: `task` stays "Task". An empty line is worse than a
  // redundant one.
  if (parts.length <= 1) return humaniseCode(stripped)
  const kept = [...parts]
  if (noise.has(kept[kept.length - 1].toLowerCase())) kept.pop()
  if (kept.length > 0 && noise.has(kept[0].toLowerCase())) kept.shift()
  if (kept.length === 0) return humaniseCode(stripped)
  return humaniseCode(kept.join('_'))
}

/**
 * `market_task` -> "Market", `write_report` -> "Write report",
 * `task_verify_claims` -> "Verify claims".
 *
 * The dropped word is the noun the surface already supplies: a trace row
 * reading "Market task started" beneath a heading that says Tasks says it
 * twice.
 */
export function humaniseTask(name: string, options: HumaniseOptions = {}): string {
  return humaniseWithout(name, TASK_NOISE, options)
}

/**
 * `research_market_landscape` -> "Research market landscape",
 * `FirecrawlScrapeWebsiteTool` -> "Firecrawl scrape website",
 * `hn_sentiment_tool` -> "HN sentiment".
 */
export function humaniseTool(name: string, options: HumaniseOptions = {}): string {
  return humaniseWithout(name, TOOL_NOISE, options)
}
