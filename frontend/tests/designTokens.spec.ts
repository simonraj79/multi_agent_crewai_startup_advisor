import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * `docs/design.md` §8's enforcement, and `DEFINITION-OF-DONE.md` T3.2's:
 * **no hex, `rgba(` or `hsl(` literal in any `.vue` or `.css` file touched on
 * this branch**, outside the token sheets that exist to hold them.
 *
 * SCOPED TO THE BRANCH, and that is the whole reason it can exist at all. The
 * rule design.md §8 states is a rule about the repository, and the repository
 * does not obey it today: run this over `frontend/src` unscoped and it names
 * more than a hundred files, most of them owned by plans nobody is working on
 * this week. A test that fails on everybody's code is a test somebody deletes.
 *
 * A test that fails on the code THIS BRANCH touched is a different instrument:
 * it cannot be inherited, it cannot accumulate, and every branch that opens a
 * sheet leaves it cleaner than it found it. `git diff --name-only main...HEAD`
 * plus the working tree is the list, so a file is in scope from the moment it
 * is edited rather than from the moment it is committed.
 *
 * WHY LITERALS ARE THE THING MEASURED. A colour written in a component is not
 * merely untidy - it is a colour that the light theme cannot reach. Every one
 * of the light-theme defects this branch fixed was one: a crew strip that stayed
 * black on paper, a scorecard track at 1.014:1, a dark chip on a light bubble.
 * The theme is a block of token redefinitions, so a value that is not a token
 * is a value that has exactly one appearance for ever.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const FRONTEND = path.resolve(HERE, '..')
const REPO = path.resolve(FRONTEND, '..')

/**
 * The sheets that are ALLOWED to hold a literal, because holding literals is
 * what they are for. This is `docs/design.md` §0's list: every stylesheet under
 * `assets/styles/` is a token or palette sheet, and a colour has to be written
 * out somewhere or the system has no values at all.
 */
const TOKEN_SHEETS = /^frontend\/src\/assets\/styles\/[^/]+\.css$/

/**
 * Literals that are not stylesheet values and cannot be tokens.
 *
 * One entry, and it is a library prop rather than CSS: Vue Flow's `<Background>`
 * takes its dot colour as a STRING attribute, not a class, so it cannot read a
 * custom property. The value mirrors `--dot-color` and `docs/design.md` §4
 * carries the pair. If this list ever grows past a handful, the right move is
 * to ask why - not to keep adding rows.
 */
const ALLOWED: Readonly<Record<string, readonly string[]>> = {
  'frontend/src/views/StudioView.vue': ['#777777'],
  'frontend/src/components/builder/BuilderCanvas.vue': ['#777777'],
}

/** `#abc`, `#aabbcc`, `#aabbccdd`, `rgba(…`, `rgb(…`, `hsl(…`, `hsla(…`. */
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g

/**
 * Who has to fix a line, from `DEFINITION-OF-DONE.md` §0's ownership table.
 *
 * Not decoration: a literal in `ChatRail.vue` cannot be fixed from `tokens.css`
 * while W3 has that file open, so a failure message that only says "there is a
 * literal" sends the wrong person looking. First match wins, and the fallback
 * is deliberately the empty string rather than a guess.
 */
const OWNERS: ReadonlyArray<readonly [RegExp, string]> = [
  [/assets\/styles\/character\.css$|characters\/|AgentCharacter\.vue$/, 'W2'],
  [/ChatRail\.vue$|DialogueRail\.vue$/, 'W3'],
  [/ReportPanel\.vue$|GateCard\.vue$|RunHistory\.vue$|WorkflowEdge\.vue$/, 'W1'],
  [/CrewProgress\.vue$|WorkflowNode\.vue$|assets\/styles\/motion\.css$/, 'W4'],
  [/studio\.css$|StatusPanel\.vue$|StudioView\.vue$|assets\/styles\/tokens\.css$/, 'W5'],
]

function ownerOf(file: string): string {
  return OWNERS.find(([pattern]) => pattern.test(file))?.[1] ?? '??'
}

/**
 * The run shell's own surfaces, named rather than derived.
 *
 * The derived half of the list below answers "what did this branch change",
 * which is the right question ON a branch and no question at all once the
 * branch is merged: `git merge-base main HEAD` on `main` is HEAD, the diff is
 * empty, and the check evaporated into its own emptiness guard. It failed
 * loudly, which is the only reason this is a five-minute fix rather than a
 * silent green that would have outlived everyone who knew what it was for.
 *
 * So the floor is explicit. These are the files that PAINT the run shell, they
 * do not move when a branch merges, and the rule stands over them for good:
 * a colour lives in a token sheet or it does not exist. Four of them are
 * filtered straight back out by `TOKEN_SHEETS` - `motion.css`,
 * `character.css`, `node-card.css` and anything else under `assets/styles/` -
 * and they are listed anyway, because a reader checking whether their file is
 * covered should find the answer here rather than by reasoning about a regex.
 */
const OWNED_SURFACES: readonly string[] = [
  'frontend/src/components/ReportPanel.vue',
  'frontend/src/components/GateCard.vue',
  'frontend/src/components/ChatRail.vue',
  'frontend/src/components/DialogueRail.vue',
  'frontend/src/components/WorkflowNode.vue',
  'frontend/src/components/CrewProgress.vue',
  'frontend/src/components/StatusPanel.vue',
  'frontend/src/components/AgentCharacter.vue',
  'frontend/src/components/HandoffToken.vue',
  'frontend/src/components/WorkflowEdge.vue',
  'frontend/src/views/StudioView.vue',
  'frontend/src/studio.css',
  'frontend/src/assets/styles/motion.css',
  'frontend/src/assets/styles/character.css',
  'frontend/src/assets/styles/node-card.css',
]

function git(...args: string[]): string {
  return execFileSync('git', args, { cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
}

/**
 * What this branch changed, or nothing if git cannot say.
 *
 * Three sources, unioned: the diff against the merge base with `main`, what is
 * modified in the working tree, and what is untracked. The third matters more
 * than it looks - a file that exists only in somebody's working copy is exactly
 * the file whose literals nobody has looked at yet.
 *
 * NEVER THROWS. A shallow CI clone has no `main` to find a merge base against,
 * a tarball export has no `.git` at all, and neither is a reason to fail a test
 * about colour literals: the answer in both cases is "git cannot say", and the
 * explicit list below carries the check on its own. The note goes to the
 * console so a run that quietly lost half its scope says so.
 */
function changedFiles(): string[] {
  try {
    const base = git('merge-base', 'main', 'HEAD').trim()
    return [
      git('diff', '--name-only', `${base}...HEAD`),
      git('diff', '--name-only', 'HEAD'),
      git('ls-files', '--others', '--exclude-standard'),
    ].join('\n').split('\n')
  } catch {
    console.log(
      'designTokens: git could not name the changed files (no repo, or no `main` '
      + 'to compare against). Checking the committed surface list only.',
    )
    return []
  }
}

/**
 * The files this check covers: the run shell's own surfaces, plus whatever else
 * this branch happens to have touched.
 *
 * The union is the point. The explicit half cannot evaporate - it is the same
 * list on a branch, on `main`, and in a clone with no history - and the derived
 * half means a branch that opens a file nobody listed still leaves it cleaner
 * than it found it.
 */
function coveredFiles(): string[] {
  const seen = new Set<string>()
  for (const line of [...OWNED_SURFACES, ...changedFiles()]) {
    const file = line.trim()
    if (!file) continue
    if (!/\.(vue|css)$/.test(file)) continue
    if (TOKEN_SHEETS.test(file)) continue
    if (!existsSync(path.join(REPO, file))) continue
    seen.add(file)
  }
  return [...seen].sort()
}

interface Hit {
  file: string
  line: number
  literal: string
  text: string
}

/**
 * Blank out comments, keeping every newline so line numbers still resolve.
 *
 * A comment is prose, and prose about a colour is not a colour: the rule at the
 * top of this file is stated in `studio.css` beside the mask that motivated it,
 * and a scanner that could not tell the two apart would make every explanation
 * of the rule a violation of it. `contrast-audit.mjs` strips comments before
 * reading a token value for exactly the same reason.
 */
function blankComments(source: string): string {
  const keepNewlines = (match: string) => match.replace(/[^\n]/g, ' ')
  return source
    .replace(/\/\*[\s\S]*?\*\//g, keepNewlines)
    .replace(/<!--[\s\S]*?-->/g, keepNewlines)
    .replace(/^[ \t]*\/\/.*$/gm, keepNewlines)
}

function literalsIn(file: string): Hit[] {
  const allowed = ALLOWED[file] ?? []
  const source = blankComments(readFileSync(path.join(REPO, file), 'utf8'))
  const hits: Hit[] = []
  source.split(/\r?\n/).forEach((text, index) => {
    for (const match of text.matchAll(LITERAL)) {
      const literal = match[0]
      if (allowed.some((ok) => text.includes(ok) && literal.startsWith(ok.slice(0, 4)))) continue
      hits.push({ file, line: index + 1, literal, text: text.trim().slice(0, 110) })
    }
  })
  return hits
}

describe('design tokens: no colour literal in a file this branch touched', () => {
  const files = coveredFiles()
  const hits = files.flatMap(literalsIn)

  it('covers the whole run shell, on a branch or on main', () => {
    // The guard that caught the defect this function was rewritten for: on
    // `main` the merge base IS HEAD, the diff is empty, and the check used to
    // evaporate into this assertion. It is now a floor rather than a pulse -
    // every surface in `OWNED_SURFACES` that survives the token-sheet filter
    // must be in the list, whatever git says.
    const expected = OWNED_SURFACES.filter(
      (file) => !TOKEN_SHEETS.test(file) && existsSync(path.join(REPO, file)),
    )
    expect(expected.length).toBeGreaterThan(0)
    for (const file of expected) expect(files).toContain(file)
  })

  it('reports the whole inventory, so the run is the evidence', () => {
    // The output of this test IS `docs/run-shell/evidence/T3/literals.txt`
    // (T3.2 names that artifact). Printed rather than written, so the file is
    // produced by redirecting a command that anyone can re-run.
    const byFile = new Map<string, number>()
    for (const file of files) byFile.set(file, 0)
    for (const hit of hits) byFile.set(hit.file, (byFile.get(hit.file) ?? 0) + 1)

    const lines = [
      `scanned ${files.length} .vue/.css files: the run shell's surfaces, plus this branch's own changes`,
      `token sheets exempt: frontend/src/assets/styles/*.css (docs/design.md §0)`,
      '',
      ...[...byFile.entries()].map(([file, n]) => `${String(n).padStart(3)}  ${file}`),
      '',
      ...(hits.length
        ? ['LITERALS FOUND:', ...hits.map((h) => `  ${h.file}:${h.line}  ${h.literal}   ${h.text}`)]
        : ['no colour literal in any of them.']),
    ]
    console.log(lines.join('\n'))
    expect(files.length).toBe(byFile.size)
  })

  it('contains no hex, rgba() or hsl() literal in a file W5 owns', () => {
    // The half of T3.2 this task can close on its own. Split from the branch
    // check below so a red suite says WHOSE work is outstanding rather than
    // only that something is - six people are editing this shell at once.
    const named = hits
      .filter((h) => ownerOf(h.file) === 'W5')
      .map((h) => `${h.file}:${h.line}  ${h.literal}   ${h.text}`)
    expect(named, named.join('\n')).toEqual([])
  })

  it('contains no hex, rgba() or hsl() literal anywhere on the branch', () => {
    // T3.2 in full. Each remaining line names the worker whose file it is and
    // the token to reach for; `docs/run-shell/SHELL-SCOPE.md` §7 is the same
    // list in prose. This goes green as the other five land, and until then it
    // is the coordination signal rather than a defect in anybody's code.
    const named = hits.map(
      (h) => `[${ownerOf(h.file)}] ${h.file}:${h.line}  ${h.literal}   ${h.text}`,
    )
    expect(named, named.join('\n')).toEqual([])
  })
})

describe('the token sheet declares what the design system says it does', () => {
  const tokens = readFileSync(
    path.join(REPO, 'frontend/src/assets/styles/tokens.css'),
    'utf8',
  )

  it('carries the eight-step spacing scale', () => {
    // design.md §3's eight house values, and no ninth. A scale with a gap in it
    // is a scale somebody works around with a literal.
    const expected = ['4px', '6px', '8px', '10px', '12px', '16px', '20px', '24px']
    expected.forEach((value, index) => {
      expect(tokens).toContain(`--space-${index + 1}: ${value};`)
    })
    expect(tokens).not.toContain('--space-9')
  })

  it('carries the seven type roles and one tracking value', () => {
    for (const role of ['display', 'title', 'body', 'label', 'kicker', 'meta', 'metric']) {
      expect(tokens).toContain(`--type-${role}:`)
    }
    expect(tokens).toContain('--track-kicker:')
  })

  it('adds no seventh type step', () => {
    // The roles resolve to the six shipped steps. A role that hardcoded a size
    // would be a seventh step wearing a role's name, which is exactly what
    // design.md §2 refuses.
    const roles = tokens.match(/--type-[a-z]+:[^;]+;/g) ?? []
    expect(roles.length).toBeGreaterThanOrEqual(7)
    for (const role of roles) {
      expect(role, `${role} must resolve a --fs-* step rather than a raw size`).toMatch(/var\(--fs-\d+\)/)
    }
  })

  it('gives every new light-theme token a dark value to shadow', () => {
    // The additive construction, asserted rather than promised: each of these
    // exists so the LIGHT theme can be corrected without a dark pixel moving,
    // so a light value with no dark declaration would be a token that changes
    // the dark theme by accident.
    const [dark, light] = tokens.split(":root[data-theme='light']")
    expect(light, 'the light block must exist').toBeTruthy()
    for (const name of [
      'text-meta',
      'border-control',
      'border-hover-strong',
      'on-accent-cyan',
      'on-accent-mint',
      'on-accent-blue',
      'link-strong',
      'warn-text-strong',
      'warn-border-strong',
      'err-border-strong',
    ]) {
      expect(dark, `--${name} needs a dark value`).toContain(`--${name}:`)
      expect(light, `--${name} needs a light value`).toContain(`--${name}:`)
    }
  })

  it('keeps the four frozen shadows out of the light block', () => {
    // Their sites are inside the builder's sixteen full-page baselines, so a
    // theme-aware value there is sixteen red screenshots. SHELL-SCOPE.md §2d.
    const [, light] = tokens.split(":root[data-theme='light']")
    for (const name of ['shadow-controls', 'shadow-rail-start', 'shadow-rail-end', 'shadow-sheet']) {
      expect(light, `--${name} must not vary by theme`).not.toContain(`--${name}:`)
    }
  })
})
