import { describe, expect, it } from 'vitest'
import { isTableDivider, renderMarkdown } from '../src/utils/markdown'

/**
 * Audit M10: the table-divider test was quadratic on a 64 KiB report body.
 *
 * The subject is `markdown_body`, which `RUN_RESULT_BODY_KEYS` deliberately
 * exempts from the 4,096-character frame clip and the server reads at 64 KiB,
 * plus any imported skill body. So a Reporter agent - or a skill file somebody
 * imports - can hand the reader's tab a line the divider test almost matches,
 * and the tab freezes.
 *
 * The budget below is a wall-clock assertion, which is normally the wrong
 * shape for a test. It is the right one here because the defect IS wall clock:
 * the shipped pattern took 4.4 s on this exact input, the repaired one takes
 * under a millisecond, and any threshold between them separates the two on any
 * machine that can run this suite at all. 200 ms leaves three orders of
 * magnitude of headroom over the fix and twenty times under the defect.
 */

/**
 * The shipped pattern, kept verbatim so the equivalence claim is checked
 * against the real thing rather than against a description of it. Nothing but
 * this test may use it - it is the defect.
 */
const SHIPPED_TABLE_DIVIDER = /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/

/**
 * 65,537 characters, of which only the last cannot belong to a divider. That
 * is the worst case: every prefix still looks like it might match, so a
 * backtracking engine tries every split before admitting the line is not one.
 */
const NEAR_MISS = `${' -'.repeat(32_768)}x`

const REDOS_BUDGET_MS = 200

describe('M10: the table divider test is linear', () => {
  it('rejects a 64 KiB near-miss line well inside the budget', () => {
    const started = performance.now()
    expect(isTableDivider(NEAR_MISS)).toBe(false)
    expect(performance.now() - started).toBeLessThan(REDOS_BUDGET_MS)
  })

  it('rejects the same line through the renderer, which is how it is reached', () => {
    // The parser only asks about line N+1 when line N looks like a table
    // header, so the pathological line needs a pipe-bearing line above it.
    const started = performance.now()
    const html = renderMarkdown(`| header |\n${NEAR_MISS}\n`)
    const elapsed = performance.now() - started
    expect(html).toBeTypeOf('string')
    expect(elapsed).toBeLessThan(REDOS_BUDGET_MS)
  })

  it('rejects a 64 KiB near-miss with no dash at all, the other pathological shape', () => {
    const started = performance.now()
    expect(isTableDivider(`${' :'.repeat(32_768)}x`)).toBe(false)
    expect(performance.now() - started).toBeLessThan(REDOS_BUDGET_MS)
  })

  it('accepts everything the shipped pattern accepted, and refuses the same non-dividers', () => {
    const rows = [
      '| --- | --- |',
      '|:---|---:|',
      ' :-: | :-- ',
      '---',
      '-',
      '	---	',
      '| - |',
      '  |  ---  |  ---  |  ',
      '',
      '   ',
      '| ::: | ::: |',
      '| abc |',
      '| --- | x |',
      '===',
      '| Dim | Score |',
      '- a bullet',
      '--- trailing words',
    ]
    for (const row of rows) {
      expect(isTableDivider(row), `divider ${JSON.stringify(row)}`).toBe(
        SHIPPED_TABLE_DIVIDER.test(row),
      )
    }
  })

  it('rejects nothing the shipped pattern accepted, and widens by exactly two strings', () => {
    // Exhaustive to length 3 over the characters either pattern can see, plus
    // one that neither may accept: 6 + 36 + 216 = 258 strings. Cheap, and it
    // settles the equivalence claim rather than sampling it.
    //
    // The claim that matters is one-directional - no divider that used to open
    // a table stops opening one - and it holds with nothing left over. The
    // other direction does NOT hold exactly, and the two strings it fails on
    // are pinned here rather than described, so a later edit that widens this
    // further has to say so.
    const alphabet = ['-', ':', '|', ' ', '	', 'x']
    const strings: string[] = []
    for (const a of alphabet) {
      strings.push(a)
      for (const b of alphabet) {
        strings.push(a + b)
        for (const c of alphabet) strings.push(a + b + c)
      }
    }
    const nowRejected = strings.filter((s) => SHIPPED_TABLE_DIVIDER.test(s) && !isTableDivider(s))
    const nowAccepted = strings.filter((s) => !SHIPPED_TABLE_DIVIDER.test(s) && isTableDivider(s))
    expect(nowRejected).toEqual([])
    // Two or more pipes before the first dash, which the old pattern's single
    // optional leading `\|?` could not span. Not a row anybody writes.
    expect(nowAccepted).toEqual([':|-', '||-'])
  })

  it('still renders the pipe table the score breakdown actually arrives as', () => {
    const html = renderMarkdown('| Dim | Score |\n| --- | --- |\n| Demand | 3 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<th>Dim</th>')
    expect(html).toContain('<td>Demand</td>')
  })

  it('still refuses to invent a table when the second row is not a divider', () => {
    expect(renderMarkdown('| Dim | Score |\n| ::: | ::: |\n')).not.toContain('<table>')
  })
})
