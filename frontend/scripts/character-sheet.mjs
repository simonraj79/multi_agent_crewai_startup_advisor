/* ---------------------------------------------------------------------------
 * character-sheet.mjs - renders the cast's evidence sheets.
 *
 *   cd frontend
 *   node scripts/character-sheet.mjs                       # all three sheets
 *   node scripts/character-sheet.mjs --roles roles.json    # G4 with more flows
 *   node scripts/character-sheet.mjs --html-only           # write HTML, no shots
 *
 * It writes, under `docs/run-shell/evidence/`:
 *
 *   T2/characters-32px.html + .png   the 32px legibility proof
 *   T2/states-32px.html    + .png    six states x two characters
 *   G4/roles-sheet.html    + .png    three flows, dark and light, 32 and 96
 *
 * THE HTML IS KEPT BESIDE THE PNG ON PURPOSE. A screenshot is a claim; the
 * page that produced it is the claim's working. A verifier can open either.
 *
 * Nothing here draws a character. Every figure is `pipSvg()` from
 * `src/characters/pip.ts` - the shipping file, imported directly (Node 24
 * strips the types), so the sheet cannot drift from the component. Every
 * colour is read out of `tokens.css` and `motion.css` at run time rather than
 * copied, so the sheet cannot drift from the palette either.
 *
 * THE 32px RASTER IS THE POINT. A vector drawn at 96px and a vector drawn at
 * 32px are the same picture on a design sheet and two different pictures on a
 * screen. Every "32px" block here rasterises the figure through a 32x32 canvas
 * and magnifies it 6x with `imageSmoothingEnabled = false`, so what is on the
 * sheet is the pixels a 32px node badge actually gets. That test found three
 * real defects in the geometry while this system was being designed; it is
 * kept because it is the only check of "reads at 32px" that is not an
 * assertion.
 *
 * `npx playwright screenshot` has NO `--device-scale-factor` (checked: --help
 * offers --viewport-size, --color-scheme, --device and nothing else of the
 * kind), so the 3x pages are the documented alternative - the same page under
 * `zoom: 3`, which re-renders every vector at 3x from the same code.
 * --------------------------------------------------------------------------- */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  BODY_NAMES,
  CREST_NAMES,
  EYE_NAMES,
  MOUTH_NAMES,
  PIP_STATES,
  characterSeed,
  pipParts,
  pipSvg,
} from '../src/characters/pip.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontend = path.resolve(here, '..')
const repo = path.resolve(frontend, '..')
const evidence = path.join(repo, 'docs', 'run-shell', 'evidence')

/* ------------------------------------------------------------ the arguments */

const argv = process.argv.slice(2)
function flag(name) {
  return argv.includes(`--${name}`)
}
function option(name) {
  const at = argv.indexOf(`--${name}`)
  return at >= 0 && at + 1 < argv.length ? argv[at + 1] : ''
}

const DEFAULT_FLOWS = [
  {
    name: 'Idea Validator',
    note: 'the six-agent flow this console shipped with',
    roles: ['Scoper', 'Market Analyst', 'Sentiment Analyst', 'Feasibility Analyst', 'Synthesist', 'Reporter'],
  },
  {
    name: 'Brief Crew',
    note: 'the original three-agent pipeline',
    roles: ['Researcher', 'Analyst', 'Writer'],
  },
  {
    name: 'Copy Desk',
    note: 'an invented flow the character system has never seen',
    roles: ['Tone Coach', 'Fact Checker', 'Localisation Lead', 'Pricing Strategist'],
  },
  {
    name: 'G1 flow',
    note: 'EMPTY - filled in by RV after the freeze',
    roles: [],
  },
]

const rolesFile = option('roles')
const FLOWS = rolesFile
  ? JSON.parse(fs.readFileSync(path.resolve(process.cwd(), rolesFile), 'utf8')).flows
  : DEFAULT_FLOWS

/* --------------------------------------------------- the palette, not copied */

/**
 * Pull one selector's custom properties out of a stylesheet.
 *
 * Read rather than copied, because a palette transcribed into a build script
 * is a second declaration of the same value and the two drift - which is the
 * single most repeated failure recorded in this repository's own notes.
 */
function extractVars(css, selector) {
  const at = css.indexOf(selector)
  if (at < 0) throw new Error(`no ${selector} block in the stylesheet`)
  const open = css.indexOf('{', at)
  const close = css.indexOf('\n}', open)
  const body = css.slice(open + 1, close)
  const vars = {}
  for (const line of body.split('\n')) {
    const match = /^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/i.exec(line)
    if (match) vars[match[1]] = match[2].trim()
  }
  return vars
}

const styles = path.join(frontend, 'src', 'assets', 'styles')
const tokensCss = fs.readFileSync(path.join(styles, 'tokens.css'), 'utf8')
const motionCss = fs.readFileSync(path.join(styles, 'motion.css'), 'utf8')
const characterCss = fs.readFileSync(path.join(styles, 'character.css'), 'utf8')

const WANTED = [
  '--bg-app',
  '--bg-node',
  '--text-primary',
  '--text-title',
  '--text-muted',
  '--border-default',
  '--warn-border',
  '--err-border',
  '--warn-text',
  '--motion-medium',
  '--ease-out',
  '--r-lg',
  '--r-2xl',
  ...Array.from({ length: 12 }, (_, index) => `--character-${index + 1}`),
]

function theme(selector) {
  const merged = { ...extractVars(tokensCss, selector), ...extractVars(motionCss, selector) }
  const out = {}
  for (const name of WANTED) if (merged[name]) out[name] = merged[name]
  return out
}

const DARK = theme(':root')
const LIGHT = { ...DARK, ...theme(":root[data-theme='light']") }

function block(selector, vars) {
  return `${selector} {\n${Object.entries(vars)
    .map(([name, value]) => `  ${name}: ${value};`)
    .join('\n')}\n}\n`
}

const THEME_CSS = block('[data-scheme="dark"]', DARK) + block('[data-scheme="light"]', LIGHT)

/* ------------------------------------------------------------- the page shell */

const PAGE_CSS = `
* { box-sizing: border-box; }
body { margin: 0; font: 13px/1.5 'Segoe UI', system-ui, sans-serif; }
.scheme { background: var(--bg-app); color: var(--text-primary); padding: 24px 28px 32px; }
h1 { font-size: 20px; margin: 0 0 4px; letter-spacing: -0.01em; }
h1 span { color: var(--text-muted); font-weight: 400; }
.lede { color: var(--text-muted); margin: 0 0 20px; max-width: 100ch; font-size: 12px; }
h2 {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--text-muted); margin: 24px 0 10px; font-weight: 600;
  border-top: 1px solid var(--border-default); padding-top: 9px;
}
h2 em { font-style: normal; color: var(--text-primary); text-transform: none; letter-spacing: 0; font-weight: 400; }
.card {
  background: var(--bg-node); border: 1px solid var(--border-default);
  border-radius: var(--r-2xl); padding: 14px 16px 12px; margin-bottom: 12px;
}
.card > h3 {
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-muted); margin: 0 0 12px; font-weight: 600;
}
.card > h3 b { color: var(--text-primary); font-weight: 600; letter-spacing: 0; text-transform: none; }
.row { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; }
.cell { text-align: center; width: 208px; }
.big { display: flex; justify-content: center; align-items: flex-end; height: 108px; }
/* The 6x magnification of a 32px raster is 192px on a side, so its box is
   sized for that. A holder shorter than its canvas is how the first draft of
   this sheet drew every card over the heading beneath it. */
.rast { display: flex; justify-content: center; align-items: flex-end; height: 196px; }
.true32 { display: flex; justify-content: center; align-items: flex-end; height: 40px; }
.name { margin-top: 5px; font-size: 11.5px; color: var(--text-primary); }
.parts { font-size: 9.5px; color: var(--text-muted); font-family: Consolas, monospace; }
.tag {
  font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-muted); margin-top: 3px;
}
canvas { display: block; image-rendering: pixelated; margin: 0 auto; }
.empty {
  border: 1px dashed var(--border-default); border-radius: var(--r-lg);
  padding: 22px 18px; color: var(--warn-text); font-size: 12.5px; text-align: center;
}
.empty code { color: var(--text-muted); font-family: Consolas, monospace; font-size: 11.5px; }
.warnlbl { color: var(--warn-text); }
`

function page(title, lede, bodyHtml, zoom = 1) {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<title>${title}</title>
<style>${THEME_CSS}${PAGE_CSS}${characterCss}</style>
</head><body${zoom > 1 ? ` style="zoom:${zoom}"` : ''}>
${bodyHtml}
<script id="figures" type="application/json">__FIGURES__</script>
<script>
(function () {
  var jobs = JSON.parse(document.getElementById('figures').textContent);
  var THEMES = __THEMES__;
  /* An <img> cannot see the page's custom properties, so the standalone copy
     resolves them to literals first. Same markup, same stylesheet, values
     baked - which is why this proves the shipping CSS and not a second one. */
  function standalone(markup, vars) {
    var css = __CSS__;
    Object.keys(vars).forEach(function (name) {
      css = css.split('var(' + name + ')').join(vars[name]);
    });
    var svg = markup.replace(/style="color:var\\(--character-(\\d+)\\)"/, function (_, n) {
      return 'style="color:' + vars['--character-' + n] + '"';
    });
    return svg.replace('>', ' xmlns="http://www.w3.org/2000/svg"><style>' + css + '</style>');
  }
  jobs.forEach(function (job) {
    var holder = document.getElementById(job.id);
    if (!holder) return;
    var vars = THEMES[job.scheme];
    var img = new Image();
    img.onload = function () {
      var a = document.createElement('canvas');
      a.width = 32; a.height = 32;
      var ac = a.getContext('2d');
      ac.fillStyle = vars['--bg-node']; ac.fillRect(0, 0, 32, 32);
      ac.drawImage(img, 0, 0, 32, 32);
      var b = document.createElement('canvas');
      b.width = 32 * job.scale; b.height = 32 * job.scale;
      var bc = b.getContext('2d');
      bc.imageSmoothingEnabled = false;
      bc.drawImage(a, 0, 0, 32 * job.scale, 32 * job.scale);
      holder.appendChild(b);
    };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(standalone(job.markup, vars));
  });
})();
</script>
</body></html>
`
}

/* -------------------------------------------------------------- the figures */

let figureSeq = 0
const figures = []

/** A 32x32 raster of one Pip, magnified `scale` times with smoothing off. */
function raster(key, state, scheme, scale = 6) {
  const id = `f${(figureSeq += 1)}`
  figures.push({ id, scheme, scale, markup: pipSvg(key, { size: 32, state }) })
  return `<div id="${id}"></div>`
}

/** The same Pip as a live vector at its true size, for the 1x comparison. */
function vector(key, state, size) {
  return pipSvg(key, { size, state })
}

function partsLabel(key) {
  const p = pipParts(characterSeed(key))
  return `${BODY_NAMES[p.body]}/${EYE_NAMES[p.eyes]}/${MOUTH_NAMES[p.mouth]}/${CREST_NAMES[p.crest]}/c${p.colour}`
}

function escapeHtml(value) {
  return String(value).replace(/[&<>]/g, (ch) => (ch === '&' ? '&amp;' : ch === '<' ? '&lt;' : '&gt;'))
}

/* ---------------------------------------------------------- sheet 1: the cast */

function castCard(title, roles, scheme) {
  const cells = roles
    .map(
      (role) =>
        `<div class="cell">` +
        `<div class="rast">${raster(role, 'idle', scheme)}</div>` +
        `<div class="tag">32px raster, 6x</div>` +
        `<div class="true32">${vector(role, 'idle', 32)}</div>` +
        `<div class="tag">32px, true size</div>` +
        `<div class="name">${escapeHtml(role)}</div>` +
        `<div class="parts">${partsLabel(role)}</div>` +
        `</div>`,
    )
    .join('')
  return `<div class="card"><h3>${title}</h3><div class="row">${cells}</div></div>`
}

function charactersSheet() {
  const dark = FLOWS.filter((flow) => flow.roles.length > 0)
    .map((flow) => castCard(`<b>${escapeHtml(flow.name)}</b> &nbsp;&middot;&nbsp; ${escapeHtml(flow.note)}`, flow.roles, 'dark'))
    .join('')
  const lightRoles = FLOWS[0]?.roles ?? []
  const light = castCard(
    `<b>${escapeHtml(FLOWS[0]?.name ?? 'flow')}</b> &nbsp;&middot;&nbsp; light theme, on a white card`,
    lightRoles,
    'light',
  )
  return page(
    'Pips - the cast at 32px',
    '',
    `<div class="scheme" data-scheme="dark">
      <h1>Pips <span>&mdash; the cast, rasterised at 32&times;32 and magnified 6&times; with smoothing off</span></h1>
      <p class="lede">Every figure below is <code>pipSvg(role)</code> from <code>src/characters/pip.ts</code>,
      the shipping generator. The large block in each cell is not a vector drawn big: it is the
      figure rasterised through a 32&times;32 canvas and magnified with <code>imageSmoothingEnabled = false</code>,
      so it is the pixels a 32px node badge actually gets. The small figure under it is the same
      character live at its true 32px, for comparison. The monospace line is the character's five
      hash-selected parts.</p>
      <h2>A &mdash; the cast on the dark theme <em>&nbsp;&middot;&nbsp; --bg-node</em></h2>
      ${dark}
     </div>
     <div class="scheme" data-scheme="light">
      <h2>B &mdash; the same six on the light theme <em>&nbsp;&middot;&nbsp; the ink inverts with --bg-node, with no second rule</em></h2>
      ${light}
     </div>`,
  )
}

/* -------------------------------------------------------- sheet 2: the states */

const STATE_NOTE = {
  idle: 'still &middot; resting mouth',
  working: 'lean + squint &middot; 2.6s bob',
  speaking: 'tip back + open &middot; 0.64s mouth',
  blocked: 'wide eyes + wilt + warn outline &middot; STILL',
  'blocked-error': 'x_x eyes + wilt + error outline &middot; STILL',
  done: 'arc eyes + grin &middot; still',
}

function stateCard(role, scheme) {
  const cells = PIP_STATES.map(
    (state) =>
      `<div class="cell">` +
      `<div class="big">${vector(role, state, 96)}</div>` +
      `<div class="tag">96px</div>` +
      `<div class="rast">${raster(role, state, scheme)}</div>` +
      `<div class="tag">32px raster, 6x</div>` +
      `<div class="true32">${vector(role, state, 32)}</div>` +
      `<div class="name${state.startsWith('blocked') ? ' warnlbl' : ''}">${state}</div>` +
      `<div class="parts">${STATE_NOTE[state]}</div>` +
      `</div>`,
  ).join('')
  return `<div class="card"><h3><b>${escapeHtml(role)}</b></h3><div class="row">${cells}</div></div>`
}

function statesSheet() {
  const roles = [FLOWS[0]?.roles?.[1] ?? 'Analyst', FLOWS[2]?.roles?.[0] ?? 'Tone Coach']
  return page(
    'Pips - the six states',
    '',
    `<div class="scheme" data-scheme="dark">
      <h1>Pips <span>&mdash; six states, two characters, at 96px and at a true 32px raster</span></h1>
      <p class="lede">One SVG, six CSS classes. All three eye layers and all five mouths are in the markup and
      exactly one of each is ever shown, so the mark count on screen stays at four.
      <strong>Idle, blocked, blocked-error and done are static.</strong> Only working and speaking loop, and
      both loops start at their reduced-motion pose &mdash; a still at t = 0 and a still with motion
      switched off are the same picture, which is why these captures can be trusted.</p>
      ${stateCard(roles[0], 'dark')}
      ${stateCard(roles[1], 'dark')}
     </div>
     <div class="scheme" data-scheme="light">
      <h2>The same states on the light theme</h2>
      ${stateCard(roles[0], 'light')}
     </div>`,
  )
}

/* --------------------------------------------------------- sheet 3: the flows */

function flowCard(flow, scheme, size) {
  if (flow.roles.length === 0) {
    return (
      `<div class="card"><h3><b>${escapeHtml(flow.name)}</b> &nbsp;&middot;&nbsp; ${escapeHtml(flow.note)}</h3>` +
      `<div class="empty">This section is deliberately EMPTY.<br />` +
      `The G1 flow does not exist yet: RV authors it after the freeze commit, and fills this in by re-running` +
      `<br /><code>node scripts/character-sheet.mjs --roles &lt;that flow's roles&gt;.json</code><br />` +
      `from <code>frontend/</code>. The characters it draws will not have been seen by the cast's builder.</div></div>`
    )
  }
  const cells = flow.roles
    .map(
      (role) =>
        `<div class="cell" style="width:${size === 96 ? 132 : 208}px">` +
        (size === 96
          ? `<div class="big">${vector(role, 'idle', 96)}</div><div class="tag">96px</div>`
          : `<div class="rast">${raster(role, 'idle', scheme)}</div><div class="tag">32px raster, 6x</div>` +
            `<div class="true32">${vector(role, 'idle', 32)}</div><div class="tag">32px, true size</div>`) +
        `<div class="name">${escapeHtml(role)}</div>` +
        `<div class="parts">${partsLabel(role)}</div>` +
        `</div>`,
    )
    .join('')
  return (
    `<div class="card"><h3><b>${escapeHtml(flow.name)}</b> &nbsp;&middot;&nbsp; ${escapeHtml(flow.note)}</h3>` +
    `<div class="row">${cells}</div></div>`
  )
}

function rolesSheet() {
  const at = (scheme, size) => FLOWS.map((flow) => flowCard(flow, scheme, size)).join('')
  return page(
    'Pips - roles across flows',
    '',
    `<div class="scheme" data-scheme="dark">
      <h1>Pips <span>&mdash; roles from ${FLOWS.length} different flows, at 96px and at a true 32px raster</span></h1>
      <p class="lede">One system, no per-flow art. Every character is a pure function of its role string,
      so a flow the cast's builder never saw gets real characters rather than a row of grey question
      marks. The last section is exactly that case: its flow was authored after the cast was frozen,
      by somebody else, and nothing about it was known when these shapes were drawn. A flow whose
      role list is empty renders as a labelled empty section rather than vanishing.</p>
      <h2>A &mdash; dark theme, 96px</h2>
      ${at('dark', 96)}
      <h2>B &mdash; dark theme, 32px raster</h2>
      ${at('dark', 32)}
     </div>
     <div class="scheme" data-scheme="light">
      <h2>C &mdash; light theme, 96px</h2>
      ${at('light', 96)}
      <h2>D &mdash; light theme, 32px raster</h2>
      ${at('light', 32)}
     </div>`,
  )
}

/* ------------------------------------------------------------------ the run */

const SHEETS = [
  { dir: 'T2', name: 'characters-32px', build: charactersSheet, width: 1500 },
  { dir: 'T2', name: 'states-32px', build: statesSheet, width: 1500 },
  { dir: 'G4', name: 'roles-sheet', build: rolesSheet, width: 1500 },
]

const written = []
for (const sheet of SHEETS) {
  figureSeq = 0
  figures.length = 0
  const html = sheet
    .build()
    .replace('__FIGURES__', JSON.stringify(figures))
    .replace('__THEMES__', JSON.stringify({ dark: DARK, light: LIGHT }))
    .replace('__CSS__', JSON.stringify(characterCss))
  const dir = path.join(evidence, sheet.dir)
  fs.mkdirSync(dir, { recursive: true })
  const htmlPath = path.join(dir, `${sheet.name}.html`)
  fs.writeFileSync(htmlPath, html, 'utf8')
  written.push({ ...sheet, htmlPath, pngPath: path.join(dir, `${sheet.name}.png`) })
  console.log(`wrote ${path.relative(repo, htmlPath)}  (${figures.length} rasterised figures)`)
}

if (flag('html-only')) {
  console.log('\n--html-only: skipping the screenshots.')
  process.exit(0)
}

for (const sheet of written) {
  const url = 'file:///' + sheet.htmlPath.split(path.sep).join('/')
  /* --wait-for-timeout, because every 32px block is drawn through an <img>
     decode and a canvas, and a screenshot taken before those resolve is a page
     of empty boxes that looks exactly like a broken generator. */
  /* `node node_modules/playwright/cli.js`, not `npx playwright`: `execFileSync`
     on Windows cannot spawn a `.cmd` shim without a shell, and reaching for a
     shell to work around that is how an argument containing a space becomes a
     silent mis-shot. The CLI is a plain JS entry point and this is it. */
  execFileSync(
    process.execPath,
    [
      path.join(frontend, 'node_modules', 'playwright', 'cli.js'),
      'screenshot',
      `--viewport-size=${sheet.width},1200`,
      '--full-page',
      '--wait-for-timeout=1500',
      url,
      sheet.pngPath,
    ],
    { cwd: frontend, stdio: 'inherit' },
  )
  console.log(`shot  ${path.relative(repo, sheet.pngPath)}`)
}
