/**
 * WCAG 2.1 contrast audit for the Validator Studio RUN SHELL, both themes.
 *
 * `docs/run-shell/DEFINITION-OF-DONE.md` T3.3 names this path, and T3.3 is the
 * criterion it answers: every text/background pairing the run shell paints must
 * measure ≥ 4.5:1, and every UI boundary ≥ 3.0:1, in dark AND light. Run from
 * `frontend/`:
 *
 *     node scripts/contrast-audit.mjs            # human-readable; exits 1 on a W5 failure
 *     node scripts/contrast-audit.mjs --markdown > ../docs/run-shell/evidence/T3/contrast.md
 *
 * Three properties are what make it worth trusting rather than merely worth
 * reading, and each was a mistake before it was a rule:
 *
 * 1. **Every colour is READ from the sheets** - `tokens.css` and `motion.css`,
 *    both themes - and nothing is typed in here. A hardcoded palette is a
 *    second palette, and the one that rots is always the one nobody looks at.
 * 2. **Every translucent token is COMPOSITED over the stack the shell really
 *    paints** before a ratio is taken: `bg-app → shell-bg → surface-overlay
 *    (a rail) → surface-well`. `--text-40` is `rgba(255,255,255,.52)` and
 *    `--surface-well` is `rgba(0,0,0,.22)`, so a hex-against-hex reading of
 *    that pair is wrong in the direction that flatters it.
 * 3. **Every row names an OWNER**, and the exit code counts only W5's. Six
 *    people are building this shell in parallel and a pairing painted in
 *    `CrewProgress.vue` cannot be fixed from `tokens.css`; a gate that failed
 *    on it would be a gate nobody could pass, so those rows are printed as
 *    `handed to W4` with the token to use and are excluded from the count.
 *    `docs/run-shell/SHELL-SCOPE.md` §7 is the same list in prose.
 *
 * A twin of the Python audit written alongside the scope proposal; the two
 * agreed to 0.01 on every shared row, which is the only reason either is worth
 * quoting.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const STYLES = path.resolve(HERE, '..', 'src', 'assets', 'styles')

// --------------------------------------------------------------------------
// colour maths
// --------------------------------------------------------------------------
const RGBA = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/

/** A CSS colour to [r, g, b, a], channels 0-255, alpha 0-1. */
export function parse(value) {
  const v = String(value).trim()
  const m = RGBA.exec(v)
  if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]]
  if (v.startsWith('#')) {
    const h = v.length === 4 ? [...v.slice(1)].map((c) => c + c).join('') : v.slice(1)
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1]
  }
  throw new Error(`unparseable colour: ${value}`)
}

/** Source-over composite. `bg` is opaque by the time it is used. */
export const over = (fg, bg) => [
  fg[0] * fg[3] + bg[0] * (1 - fg[3]),
  fg[1] * fg[3] + bg[1] * (1 - fg[3]),
  fg[2] * fg[3] + bg[2] * (1 - fg[3]),
  1,
]

const chan = (v) => {
  const s = v / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}
export const luminance = (c) => 0.2126 * chan(c[0]) + 0.7152 * chan(c[1]) + 0.0722 * chan(c[2])

export function ratio(fg, bg) {
  const a = luminance(fg)
  const b = luminance(bg)
  const [hi, lo] = a >= b ? [a, b] : [b, a]
  return (hi + 0.05) / (lo + 0.05)
}

// --------------------------------------------------------------------------
// token loading
// --------------------------------------------------------------------------

/**
 * `--on-accent-cyan: var(--accent-cyan)` is a real declaration and a deliberate
 * one - in the dark theme the readable colour IS the identity colour, which is
 * what makes the whole construction additive. So an alias has to be followed
 * rather than parsed. Bounded to eight hops, because a cycle in a stylesheet is
 * a bug this script should name rather than hang on.
 */
function resolve(tokens, name, hops = 0) {
  const raw = tokens[name]
  if (raw === undefined) return undefined
  const alias = /^var\(\s*--([\w-]+)\s*\)$/.exec(raw.trim())
  if (!alias) return raw
  if (hops > 8) throw new Error(`--${name} aliases in a cycle`)
  return resolve(tokens, alias[1], hops + 1)
}

function loadTokens() {
  const dark = {}
  const light = {}
  for (const file of ['tokens.css', 'motion.css']) {
    // comments stripped first, so a hex quoted in prose is never read as a value
    const text = readFileSync(path.join(STYLES, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
    const blocks = text.matchAll(/(:root(?:\[data-theme=['"]light['"]\])?)\s*\{([\s\S]*?)\n\}/g)
    for (const [, selector, body] of blocks) {
      const target = selector.includes('light') ? light : dark
      for (const [, name, value] of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
        target[name] = value.trim()
      }
    }
  }
  const merged = { ...dark, ...light }
  const flatten = (t) => Object.fromEntries(Object.keys(t).map((k) => [k, resolve(t, k)]))
  return { dark: flatten(dark), light: flatten(merged) }
}

// --------------------------------------------------------------------------
// the run shell's real surface stack, read off studio.css
//   body             background-color: var(--bg-app)
//   .studio-shell    background: var(--shell-bg)
//   .app-header      background: var(--header-bg)
//   .graph-workspace background: var(--canvas-bg) = var(--surface-panel)
//   .chat-rail / .control-rail  background: var(--surface-overlay)
// --------------------------------------------------------------------------
function surfaces(t) {
  const app = parse(t['bg-app'])
  const node = parse(t['bg-node'])
  const shell = over(parse(t['shell-bg']), app)
  const rail = over(parse(t['surface-overlay']), shell)
  const canvas = over(parse(t['surface-panel']), shell)
  return {
    'bg-app': app,
    'bg-node (card)': node,
    'app-header': over(parse(t['header-bg']), shell),
    'canvas ground': canvas,
    rail,
    'well in rail': over(parse(t['surface-well']), rail),
    'raised in rail': over(parse(t['surface-raised']), rail),
    'well on card': over(parse(t['surface-well']), node),
    'well on canvas': over(parse(t['surface-well']), canvas),
    'warn-bg over rail': over(parse(t['warn-bg']), rail),
    'err-bg over rail': over(parse(t['err-bg']), rail),
    'warn-bg over canvas': over(parse(t['warn-bg']), canvas),
    'surface-panel over bg-app': over(parse(t['surface-panel']), app),
    /*
     * THE THREE VERDICT BADGES, which are the one place a colour that was
     * chosen as TEXT is used as a FILL.
     *
     * They are surfaces in their own right and have to be listed as such: a
     * pairing measured against "a rail" says nothing about ink sitting on a
     * solid `--err-text` chip. Two of the three invert between themes, because
     * a text colour on a pale tint has to be dark and a text colour on a dark
     * tint has to be pale - which is exactly why the ink on them cannot be one
     * value. `--accent-mint` is shared across themes, so the third does not
     * move, and it is listed anyway so the set is complete.
     */
    'the warn badge': parse(t['warn-text']),
    'the err badge': parse(t['err-text']),
    'the pass badge': parse(t['accent-mint']),
  }
}

// --------------------------------------------------------------------------
// The pairings the run shell actually paints.
//
//   kind  'text' -> AA 1.4.3 needs 4.5 | 'ui' -> AA 1.4.11 needs 3.0
//   owner 'W5'   -> this task's own file; the exit code counts these
//         'W1'/'W3'/'W4'/'W2' -> another worker's file. Printed with the token
//                                to use; SHELL-SCOPE.md §7 is the same list.
// --------------------------------------------------------------------------
const PAIRS = [
  // ---- the application chrome, W5 ----------------------------------------
  ['body text on the app ground', 'text-body', 'bg-app', 'studio.css body', 'text', 'W5', ''],
  ['muted text on the header', 'text-muted', 'app-header', 'studio.css .workflow-name', 'text', 'W5', ''],
  ['meta text on the header', 'text-meta', 'app-header', 'studio.css .live-status', 'text', 'W5', ''],
  ['brand mark on the header', 'on-accent-cyan', 'app-header', 'studio.css .brand-mark', 'ui', 'W5', ''],
  ['brand M2 on the header', 'on-accent-mint', 'app-header', 'studio.css .brand-lockup span', 'text', 'W5', ''],
  ['canvas kicker on the canvas', 'on-accent-cyan', 'canvas ground', 'studio.css .canvas-kicker', 'text', 'W5', ''],
  ['canvas meta on the canvas', 'text-muted', 'canvas ground', 'studio.css .canvas-meta span', 'text', 'W5', ''],
  ['canvas version code on a well', 'text-meta', 'well on canvas', 'studio.css .canvas-meta code', 'text', 'W5', ''],
  ['the version chip boundary', 'border-control', 'well on canvas', 'studio.css .canvas-meta code', 'ui', 'W5', ''],
  ['reconnect strip on its tint', 'warn-text-strong', 'warn-bg over canvas', 'studio.css .stream-reconnecting', 'text', 'W5', ''],
  ['reconnect strip boundary', 'warn-border-strong', 'warn-bg over canvas', 'studio.css .stream-reconnecting', 'ui', 'W5', ''],
  ['a hover boundary on a rail', 'border-hover-strong', 'rail', 'studio.css .icon-button:hover', 'ui', 'W5', ''],
  ['a markdown link over the canvas', 'link-strong', 'canvas ground', 'studio.css .markdown-body a', 'text', 'W5', ''],
  ['a markdown code chip', 'on-accent-mint', 'well on canvas', 'studio.css .markdown-body code', 'text', 'W5', ''],
  ['the handoff banner', 'on-accent-cyan', 'rail', 'StudioView.vue .handoff-banner', 'text', 'W5', ''],
  ['the handoff banner code chip', 'on-accent-mint', 'well in rail', 'StudioView.vue .handoff-banner code', 'text', 'W5', ''],

  // ---- the right rail, W5 -------------------------------------------------
  ['body text in a rail', 'text-body', 'rail', 'StatusPanel.vue .read-only-well', 'text', 'W5', ''],
  ['title text on a well in a rail', 'text-title', 'well in rail', 'StatusPanel.vue .metrics-grid dd', 'text', 'W5', ''],
  ['body text on a well in a rail', 'text-body', 'well in rail', 'StatusPanel.vue textarea', 'text', 'W5', ''],
  ['muted text in a rail', 'text-muted', 'rail', 'StatusPanel.vue .control-hint', 'text', 'W5', ''],
  ['a section kicker in a rail', 'text-meta', 'rail', 'StatusPanel.vue .control-label', 'text', 'W5', ''],
  ['a metric label on a well', 'text-meta', 'well in rail', 'StatusPanel.vue .metrics-grid dt', 'text', 'W5', ''],
  ['the stream line in a rail', 'text-meta', 'rail', 'StatusPanel.vue .stream-line', 'text', 'W5', ''],
  ['the workflow version mark', 'on-accent-cyan', 'well in rail', 'StatusPanel.vue .read-only-well .version', 'text', 'W5', ''],
  ['a control boundary on a well', 'border-control', 'well in rail', 'StatusPanel.vue textarea', 'ui', 'W5', ''],
  ['a control boundary on a rail', 'border-control', 'rail', 'studio.css .segmented', 'ui', 'W5', ''],
  ['the metrics grid rule', 'border-control', 'well in rail', 'studio.css .metrics-grid', 'ui', 'W5', ''],
  ['muted text on raised in a rail', 'text-muted', 'raised in rail', 'studio.css .button-quiet', 'text', 'W5', ''],
  ['status: in flight', 'on-accent-cyan', 'rail', 'StatusPanel.vue .is-tone-active', 'text', 'W5', ''],
  ['status: needs you', 'warn-text-strong', 'rail', 'StatusPanel.vue .is-tone-attention', 'text', 'W5', ''],
  ['status: finished', 'on-accent-mint', 'rail', 'StatusPanel.vue .is-tone-done', 'text', 'W5', ''],
  ['status: failed', 'err-text', 'rail', 'StatusPanel.vue .is-tone-failed', 'text', 'W5', ''],
  ['a warn banner on its tint', 'warn-text-strong', 'warn-bg over rail', 'StatusPanel.vue .panel-banner.is-warn', 'text', 'W5', ''],
  ['a warn banner boundary', 'warn-border-strong', 'warn-bg over rail', 'StatusPanel.vue .panel-banner.is-warn', 'ui', 'W5', ''],
  ['an error banner on its tint', 'err-text', 'err-bg over rail', 'StatusPanel.vue .panel-banner.is-error', 'text', 'W5', ''],
  ['an error banner boundary', 'err-border-strong', 'err-bg over rail', 'StatusPanel.vue .panel-banner.is-error', 'ui', 'W5', ''],

  // ---- painted in another worker's file -----------------------------------
  ['a trace bubble in a rail', 'text-body', 'rail', 'ChatRail.vue .trace-bubble', 'text', 'W3', ''],
  ['a rail kicker', 'accent-cyan', 'rail', 'ChatRail.vue .section-kicker', 'text', 'W3', 'var(--on-accent-cyan)'],
  ['a text button on raised', 'link-cyan', 'raised in rail', 'ChatRail.vue .text-button', 'text', 'W3', 'var(--link-strong)'],
  ['a text button on a well', 'link-cyan', 'well in rail', 'DialogueRail.vue .text-button', 'text', 'W3', 'var(--link-strong)'],
  ['a call chip in a bubble', 'text-muted', 'well in rail', 'ChatRail.vue .call-chip', 'text', 'W3', 'background: var(--surface-well), not rgba(0,0,0,.2)'],
  ['the crew marker on the canvas', 'text-40', 'canvas ground', 'CrewProgress.vue .crew-marker', 'text', 'W4', 'var(--text-meta)'],
  ['a crew label on the canvas', 'accent-cyan', 'canvas ground', 'CrewProgress.vue .crew-label', 'text', 'W4', 'var(--on-accent-cyan)'],
  ['a crew kind as text', 'accent-blue', 'rail', 'CrewProgress.vue crew kind', 'text', 'W4', 'var(--on-accent-blue)'],
  ['a crew pip as a UI mark', 'accent-mint', 'canvas ground', 'CrewProgress.vue .crew-pip', 'ui', 'W4', 'var(--on-accent-mint)'],
  ['card meta on a card', 'text-40', 'bg-node (card)', 'node-card.css .node-meta', 'text', 'W4', 'var(--text-meta)'],
  ['body text on a card', 'text-body', 'bg-node (card)', 'node-card.css', 'text', 'W4', ''],
  // The verdict badge's ink. W5's, because the fix is a token pair rather than
  // a component change: `tokens.css` is explicit that nothing outside it knows
  // a theme exists, and this needed one ink per theme.
  ['the verdict badge, needs work', 'ink-on-warn', 'the warn badge', 'ReportPanel.vue .verdict-badge.is-warn', 'text', 'W5', ''],
  ['the verdict badge, reject', 'ink-on-err', 'the err badge', 'ReportPanel.vue .verdict-badge.is-fail', 'text', 'W5', ''],
  ['the verdict badge, validate', 'ink-on-brand', 'the pass badge', 'ReportPanel.vue .verdict-badge.is-pass', 'text', 'W5', ''],

  ['a report link', 'link-cyan', 'rail', 'ReportPanel.vue .report-sources a', 'text', 'W1', 'var(--link-strong)'],
  ['a report score on a well', 'text-primary', 'well in rail', 'ReportPanel.vue .score-value', 'text', 'W1', ''],
  ['the gate card boundary', 'warn-border', 'warn-bg over rail', 'GateCard.vue .gate-card', 'ui', 'W1', 'var(--warn-border-strong)'],
  ['the focus ring on the app ground', 'on-accent-cyan', 'bg-app', 'studio.css :focus-visible', 'ui', 'W5', ''],
]

/**
 * The twelve character colours, on the four grounds a character is drawn on.
 * `motion.css` is W4's and W2's; the whole family is handed over as one row per
 * failure rather than one per component.
 */
const CHAR_SURFACES = [
  ['bg-node (card)', 'motion.css .node-character'],
  ['bg-app', 'an avatar on the app ground'],
  ['rail', 'DialogueRail.vue .dialogue-avatar'],
  ['canvas ground', 'CrewProgress.vue .crew-medallion'],
]

function evaluate(tok, surf, theme) {
  const rows = []
  const push = (label, fgToken, bgKey, site, kind, owner, fix) => {
    if (!(fgToken in tok) || tok[fgToken] === undefined) {
      rows.push({ theme, label, fg: `--${fgToken}`, bg: bgKey, r: NaN,
        need: kind === 'text' ? 4.5 : 3, kind, owner, site: `${site}  (TOKEN NOT DECLARED)`, fix })
      return
    }
    const bg = surf[bgKey]
    const fg = over(parse(tok[fgToken]), bg)
    rows.push({ theme, label, fg: `--${fgToken}`, bg: bgKey, r: ratio(fg, bg),
      need: kind === 'text' ? 4.5 : 3, kind, owner, site, fix })
  }

  for (const [label, fgToken, bgKey, site, kind, owner, fix] of PAIRS) {
    push(label, fgToken, bgKey, site, kind, owner, fix)
  }
  for (let i = 1; i <= 12; i += 1) {
    const name = `character-${i}`
    if (!(name in tok)) continue
    for (const [bgKey, site] of CHAR_SURFACES) {
      push(`${name} as small text on ${bgKey}`, name, bgKey, site, 'text', 'W4',
        'darken in the light block only')
      push(`${name} as a UI mark on ${bgKey}`, name, bgKey, site, 'ui', 'W4', '')
    }
  }
  return rows
}

function main() {
  const markdown = process.argv.includes('--markdown')
  const { dark, light } = loadTokens()
  const rows = [
    ...evaluate(dark, surfaces(dark), 'dark'),
    ...evaluate(light, surfaces(light), 'light'),
  ]
  const failed = (row) => !(row.r >= row.need)
  const mine = rows.filter((row) => row.owner === 'W5')
  const myFailures = mine.filter(failed)
  const handed = rows.filter((row) => row.owner !== 'W5' && failed(row))
  const n = (row) => (Number.isNaN(row.r) ? '—' : row.r.toFixed(2))

  if (markdown) {
    console.log('# Contrast — the run shell, both themes\n')
    console.log('Generated by `node scripts/contrast-audit.mjs --markdown` from `frontend/`.')
    console.log('Every colour is read from `tokens.css` and `motion.css`; every translucent')
    console.log('token is composited over the surface stack `studio.css` actually paints.')
    console.log('`need` is 4.5 for text (WCAG 1.4.3 AA) and 3.0 for a UI boundary (1.4.11).\n')
    console.log(`**${rows.length} pairings. ${mine.length} are W5's and ${myFailures.length} of those fail.**`)
    console.log(`${handed.length} failing rows belong to another worker's file and are listed`)
    console.log('separately with the token to use; `docs/run-shell/SHELL-SCOPE.md` §7 is the')
    console.log('same list in prose. The exit code counts W5\'s rows only.\n')
    console.log('| theme | pair | fg token | background | ratio | need | verdict | owner | site |')
    console.log('| --- | --- | --- | --- | ---: | ---: | :---: | :---: | --- |')
    for (const row of rows) {
      const verdict = failed(row) ? (row.owner === 'W5' ? '**FAIL**' : `handed to ${row.owner}`) : 'pass'
      console.log(`| ${row.theme} | ${row.label} | \`${row.fg}\` | ${row.bg} | ${n(row)} | ${row.need} | ${verdict} | ${row.owner} | ${row.site} |`)
    }
    console.log('\n## Handed over — the token to use\n')
    console.log('| owner | theme | pair | ratio | need | site | use |')
    console.log('| :---: | --- | --- | ---: | ---: | --- | --- |')
    for (const row of handed) {
      console.log(`| **${row.owner}** | ${row.theme} | ${row.label} | ${n(row)} | ${row.need} | ${row.site} | ${row.fix || '—'} |`)
    }
    console.log(`\n${myFailures.length === 0
      ? 'Every pairing this task owns passes in both themes.'
      : `${myFailures.length} of W5's own pairings still fail.`}`)
  } else {
    for (const theme of ['dark', 'light']) {
      console.log('='.repeat(110))
      console.log(`${theme.toUpperCase()} THEME`)
      console.log('='.repeat(110))
      for (const row of rows) {
        if (row.theme !== theme) continue
        const verdict = failed(row) ? (row.owner === 'W5' ? 'FAIL' : `->${row.owner}`) : 'ok'
        console.log(`${n(row).padStart(6)}  need ${String(row.need).padEnd(4)} ${verdict.padStart(5)}  ${row.label}   [${row.fg} on ${row.bg}]  ${row.site}`)
      }
      console.log()
    }
    console.log('='.repeat(110))
    console.log("W5'S OWN FAILURES - the ones this exit code counts")
    console.log('='.repeat(110))
    for (const row of myFailures) {
      console.log(`  ${row.theme.padEnd(5)} ${n(row).padStart(5)} < ${row.need}  ${row.label}  [${row.fg} on ${row.bg}]  ${row.site}`)
    }
    if (!myFailures.length) console.log('  none.')
    console.log('')
    console.log('='.repeat(110))
    console.log('HANDED OVER - a real failure in a file this task must not open')
    console.log('='.repeat(110))
    for (const row of handed) {
      console.log(`  ${row.owner}  ${row.theme.padEnd(5)} ${n(row).padStart(5)} < ${row.need}  ${row.label}  ${row.site}  ${row.fix ? `-> ${row.fix}` : ''}`)
    }
    console.log(`\n  ${rows.length} pairings; ${mine.length} owned here, ${myFailures.length} failing; ${handed.length} handed over.`)
  }
  process.exitCode = myFailures.length ? 1 : 0
}

main()
