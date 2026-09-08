import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AdminBar from '../src/components/admin/AdminBar.vue'
import AdminColumns from '../src/components/admin/AdminColumns.vue'
import { money, shareOf } from '../src/components/admin/adminFormat'

/**
 * Every chart is markup this repository already knows how to theme.
 *
 * `.agent/plans/17-admin-console.md` criterion 25: inline SVG or a CSS bar in
 * the `BudgetMeter.vue` idiom — `role="progressbar"`, a tone **class**, a
 * computed width — **no charting dependency**, `package.json` unchanged, one
 * hue per chart, no new token, and no colour literal anywhere.
 *
 * THE DEPENDENCY HALF IS ASSERTED AGAINST THE MANIFEST, not against an import
 * list, because an import list is the thing a chart library would be added to.
 * The colour half is asserted against the source, because a literal is a
 * colour the light theme can never reach — the rule `designTokens.spec.ts`
 * enforces branch-wide, restated here over the files this plan adds so a red
 * says WHICH screen is wrong.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const FRONTEND = path.resolve(HERE, '..')
const ADMIN_DIR = path.join(FRONTEND, 'src/components/admin')

/** `#abc`, `#aabbcc`, `rgba(…`, `hsl(…` — `designTokens.spec.ts`'s pattern. */
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g

/** Comments are prose about the rule, not violations of it. */
function blankComments(source: string): string {
  const keepNewlines = (match: string) => match.replace(/[^\n]/g, ' ')
  return source
    .replace(/\/\*[\s\S]*?\*\//g, keepNewlines)
    .replace(/<!--[\s\S]*?-->/g, keepNewlines)
    .replace(/^[ \t]*\/\/.*$/gm, keepNewlines)
}

function adminSources(): string[] {
  const own = readdirSync(ADMIN_DIR).map((name) => path.join(ADMIN_DIR, name))
  return [
    ...own,
    path.join(FRONTEND, 'src/views/AdminView.vue'),
  ].filter((file) => /\.(vue|css|ts)$/.test(file))
}

describe('the charts are the BudgetMeter idiom, not a library', () => {
  it('adds no npm dependency', () => {
    const manifest = JSON.parse(
      readFileSync(path.join(FRONTEND, 'package.json'), 'utf8'),
    ) as { dependencies?: Record<string, string>; devDependencies?: Record<string, string> }
    const names = [
      ...Object.keys(manifest.dependencies ?? {}),
      ...Object.keys(manifest.devDependencies ?? {}),
    ].join(' ')
    // Named rather than counted: a count would go red the day somebody adds a
    // linter, which is not what this rule is about.
    for (const charting of ['chart.js', 'd3', 'recharts', 'apexcharts', 'echarts', 'plotly', 'vue-chartjs']) {
      expect(names, charting).not.toContain(charting)
    }
  })

  it('imports no charting module in any admin file', () => {
    for (const file of adminSources()) {
      const source = blankComments(readFileSync(file, 'utf8'))
      expect(source, file).not.toMatch(/from\s+['"](chart\.js|d3|recharts|echarts|apexcharts)/)
    }
  })

  it('writes no colour literal in any file this console adds', () => {
    // The same rule `designTokens.spec.ts` applies branch-wide, restated over
    // this plan's own files so the failure names the screen. A colour written
    // in a component is a colour the light theme cannot reach.
    const hits: string[] = []
    for (const file of adminSources()) {
      const source = blankComments(readFileSync(file, 'utf8'))
      source.split(/\r?\n/).forEach((text, index) => {
        for (const match of text.matchAll(LITERAL)) {
          hits.push(`${path.relative(FRONTEND, file)}:${index + 1}  ${match[0]}  ${text.trim().slice(0, 90)}`)
        }
      })
    }
    expect(hits, hits.join('\n')).toEqual([])
  })

  it('paints every bar and column through a tone class, never an inline colour', () => {
    const sheet = readFileSync(path.join(ADMIN_DIR, 'admin.css'), 'utf8')
    // ONE HUE PER CHART, and the mapping is the subject rather than the value:
    // money is cyan, people mint, refusals and errors warn/err.
    expect(sheet).toContain('.admin-bar.is-money .admin-bar-fill { background: var(--accent-cyan); }')
    expect(sheet).toContain('.admin-bar.is-people .admin-bar-fill { background: var(--accent-mint); }')
    expect(sheet).toContain('.admin-bar.is-warn .admin-bar-fill { background: var(--warn-text); }')
    expect(sheet).toContain('.admin-bar.is-err .admin-bar-fill { background: var(--err-text); }')
    // The SVG chart carries its hue as `color` and every rect is
    // `fill="currentColor"`, so one class recolours the whole picture.
    expect(sheet).toContain('.admin-columns.is-money { color: var(--accent-cyan); }')
    expect(readFileSync(path.join(ADMIN_DIR, 'AdminColumns.vue'), 'utf8')).toContain(
      'fill="currentColor"',
    )
  })

  it('declares no new token', () => {
    // A chart that needed a colour the system does not have would be a chart
    // asking for a design decision nobody made. Every value it uses already
    // exists in `tokens.css`.
    const tokens = readFileSync(path.join(FRONTEND, 'src/assets/styles/tokens.css'), 'utf8')
    const used = new Set(
      [...blankComments(readFileSync(path.join(ADMIN_DIR, 'admin.css'), 'utf8')).matchAll(/var\((--[a-z0-9-]+)\)/g)].map(
        (match) => match[1],
      ),
    )
    expect(used.size).toBeGreaterThan(10)
    for (const name of used) expect(tokens, `${name} is not declared`).toContain(`${name}:`)
  })
})

describe('AdminBar is a progressbar with a computed width', () => {
  function bar(props: Partial<Record<string, unknown>> = {}) {
    return mount(AdminBar, {
      props: { label: 'gemini-3.8-flash', value: 1, total: 4, display: '$1.02', ...props },
    })
  }

  it('declares role, bounds and a value a reader can hear', () => {
    const track = bar().get('[role="progressbar"]')
    expect(track.attributes('aria-valuemin')).toBe('0')
    expect(track.attributes('aria-valuemax')).toBe('100')
    expect(track.attributes('aria-valuenow')).toBe('25')
    expect(track.attributes('aria-valuetext')).toBe('gemini-3.8-flash: $1.02')
  })

  it('computes the fill width from the share', () => {
    expect(bar().get('.admin-bar-fill').attributes('style')).toContain('width: 25%')
    expect(bar({ value: 4 }).get('.admin-bar-fill').attributes('style')).toContain('width: 100%')
  })

  it('clamps rather than overflowing when a row exceeds the total', () => {
    // A row bigger than its own denominator is possible on a truncated scan:
    // the bar must be full, not 300px wide.
    expect(bar({ value: 9 }).get('.admin-bar-fill').attributes('style')).toContain('width: 100%')
  })

  it('draws nothing and claims nothing when the total is zero', () => {
    // A percentage of nothing is undefined, not zero. `aria-valuenow` is
    // omitted rather than reported as 0, and the row keeps its label and its
    // figure - which is the part that carries the fact.
    const empty = bar({ value: 0, total: 0 })
    const track = empty.get('[role="progressbar"]')
    expect(track.attributes('aria-valuenow')).toBeUndefined()
    expect(track.get('.admin-bar-fill').attributes('style')).toContain('width: 0%')
    expect(empty.text()).toContain('$1.02')
  })

  it('carries the tone as a class rather than a colour', () => {
    expect(bar({ tone: 'people' }).classes()).toContain('is-people')
    expect(bar({ tone: 'err' }).classes()).toContain('is-err')
    expect(bar().html()).not.toMatch(/background:\s*(#|rgb|hsl)/)
  })
})

describe('AdminColumns is inline SVG, one rect per day', () => {
  const POINTS = [
    { key: '2026-09-01', label: '1 Sep', value: 0.42, display: '$0.42' },
    { key: '2026-09-02', label: '2 Sep', value: 0.11, display: '$0.11' },
    { key: '2026-09-03', label: '3 Sep', value: 0, display: '$0.00' },
  ]

  function columns(points = POINTS) {
    return mount(AdminColumns, { props: { points, tone: 'money', unit: 'USD' } })
  }

  it('draws one rect per point inside one svg', () => {
    const wrapper = columns()
    expect(wrapper.findAll('svg')).toHaveLength(1)
    expect(wrapper.findAll('rect')).toHaveLength(3)
  })

  it('makes every mark a progressbar with its own day and figure', () => {
    // Each column is readable on its own: a single `img` with an alt string
    // would give a screen-reader user one sentence somebody wrote instead of
    // three readings of the data.
    const marks = columns().findAll('[role="progressbar"]')
    expect(marks).toHaveLength(3)
    expect(marks[0].attributes('aria-valuetext')).toBe('1 Sep: $0.42')
    expect(marks[0].attributes('aria-valuenow')).toBe('100')
    expect(marks[1].attributes('aria-valuenow')).toBe('26')
  })

  it('gives an empty day a hairline rather than nothing', () => {
    // A zero must be visibly a zero and not a missing bucket.
    const zero = columns().findAll('rect')[2]
    expect(Number(zero.attributes('height'))).toBeGreaterThan(0)
    expect(Number(zero.attributes('height'))).toBeLessThan(1)
  })

  it('stretches to its box rather than measuring one', () => {
    // `preserveAspectRatio="none"` over a fixed user-space box is what makes
    // this responsive with no ResizeObserver - the settling-fit trap
    // `BuilderCanvas.vue` paid for once.
    const svg = columns().get('svg')
    expect(svg.attributes('viewBox')).toBe('0 0 100 40')
    expect(svg.attributes('preserveAspectRatio')).toBe('none')
  })

  it('says a measured zero is a zero when there is no series at all', () => {
    const wrapper = columns([])
    expect(wrapper.findAll('rect')).toHaveLength(0)
    expect(wrapper.text()).toContain('measured zero')
  })
})

describe('the shared number rules', () => {
  it('never rounds a real cost to nothing, and never prints a fake zero', () => {
    expect(money(0)).toBe('$0.00')
    expect(money(0.0001)).toBe('$0.0001')
    expect(money(1.235)).toBe('$1.24')
    // `—` rather than `$0.00` for "the server did not answer": free and
    // unpriced had one spelling once, and it cost 128,069 tokens.
    expect(money(null)).toBe('—')
    expect(money(undefined)).toBe('—')
    expect(money(Number.NaN)).toBe('—')
  })

  it('answers null for a share of nothing', () => {
    expect(shareOf(1, 0)).toBeNull()
    expect(shareOf(1, 4)).toBe(25)
    expect(shareOf(9, 4)).toBe(100)
  })
})
