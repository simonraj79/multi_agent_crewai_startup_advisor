import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BrandLockup from '../src/components/BrandLockup.vue'
import BrandMark from '../src/components/BrandMark.vue'
import { PRODUCT_NAME, PRODUCT_SENTENCE, pageTitle } from '../src/data/brand'

/**
 * `docs/ux-shell/DEFINITION-OF-DONE.md` row U5: one brand, spelled once.
 *
 * WHAT THIS FILE IS FOR, and it is narrower than "the brand looks right". Four
 * of the five things U5 names are values that live in files which cannot read
 * each other - `index.html` is parsed before any stylesheet, `favicon.svg` is
 * fetched by the browser and never by the app, and `tokens.css` is the only
 * place a colour is allowed to be written down. Every one of those pairs is a
 * duplication that a person has to keep in step by remembering, and the whole
 * argument of this repository is that nobody does. So each pair is asserted
 * here: change a token and the favicon fails, change the product's name and the
 * tab title fails, redraw the mark and the icon fails.
 *
 * What it CANNOT check is whether the mark reads at 16px. That was answered by
 * rendering it at 16, 20, 32, 48 and 96 in both themes and looking
 * (`frontend/test-results/w3/candidates*.png`, `favicon-check.png`,
 * `mark-16px-*.png`), which is the only instrument there is for that question.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const FRONTEND = path.resolve(HERE, '..')

const read = (rel: string) => readFileSync(path.join(FRONTEND, rel), 'utf8')

/** The stock Vite bolt this repository shipped from its first commit until U5. */
const STOCK_FAVICON_MD5 = '7e840862161341271697daa99a40d76b'
const STOCK_FAVICON_FILL = '#863bff'

/**
 * A custom property's value, read from the one sheet allowed to hold one.
 *
 * Deliberately not a hardcoded table of hexes: a table would be a second
 * palette, and the one that rots is always the one nobody looks at
 * (`scripts/contrast-audit.mjs` opens with the same sentence). The DARK block
 * is the one read, because it is the unconditional `:root` and the favicon has
 * no theme to be in.
 */
function darkToken(name: string): string {
  const sheet = read('src/assets/styles/tokens.css')
  const light = sheet.indexOf(":root[data-theme='light']")
  const root = light === -1 ? sheet : sheet.slice(0, light)
  const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(root)
  if (!match) throw new Error(`tokens.css declares no --${name}`)
  return match[1].trim()
}

/**
 * Every `.vue`, `.ts` and `.css` file under `src/`, which is where a second
 * spelling hides.
 *
 * `.css` was added on 2026-09-06, because the scan had already missed one.
 * U5's own grep (`docs/ux-shell/VERDICT.md` §2) answered `src/studio.css:1165`
 * - the retired product name, quoted inside a comment - while every assertion
 * below it stayed green, for the single reason that this walk did not open a
 * stylesheet. `studio.css` is the file that names every brand class and
 * carries this shell's reasoning in prose; excluding it made the scan agree
 * with itself rather than with the criterion.
 */
function sourceFiles(): string[] {
  const found: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = path.join(dir, entry)
      if (statSync(full).isDirectory()) {
        walk(full)
        continue
      }
      if (/\.(vue|ts|css)$/.test(entry)) found.push(path.relative(FRONTEND, full).replace(/\\/g, '/'))
    }
  }
  walk(path.join(FRONTEND, 'src'))
  return found.sort()
}

function hits(pattern: RegExp): string[] {
  const found: string[] = []
  for (const file of sourceFiles()) {
    read(file).split(/\r?\n/).forEach((line, index) => {
      if (pattern.test(line)) found.push(`${file}:${index + 1}  ${line.trim().slice(0, 100)}`)
    })
  }
  return found
}

describe('the favicon is this product’s own, and its colours are tokens', () => {
  const favicon = read('public/favicon.svg')

  it('is no longer the stock Vite bolt', () => {
    const md5 = createHash('md5').update(readFileSync(path.join(FRONTEND, 'public/favicon.svg'))).digest('hex')
    expect(md5).not.toBe(STOCK_FAVICON_MD5)
    expect(favicon.toLowerCase()).not.toContain(STOCK_FAVICON_FILL)
  })

  it('carries the VALUES of the three tokens its comment names', () => {
    // The whole point of the pair. `favicon.svg` is the one file in the product
    // that cannot read a custom property, so it holds three literals - and this
    // is what stops them becoming three literals nobody can trace. A token
    // change fails here instead of leaving the tab icon a generation behind.
    for (const token of ['bg-app', 'accent-cyan', 'accent-mint']) {
      const value = darkToken(token)
      expect(value, `--${token} should be a hex so the favicon can carry it`).toMatch(/^#[0-9a-f]{6}$/i)
      expect(favicon.toLowerCase(), `favicon.svg does not carry --${token} (${value})`)
        .toContain(value.toLowerCase())
    }
  })

  it('holds no colour the tokens do not account for', () => {
    const allowed = ['bg-app', 'accent-cyan', 'accent-mint'].map((t) => darkToken(t).toLowerCase())
    const literals = [...favicon.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toLowerCase())
    expect([...new Set(literals)].filter((c) => !allowed.includes(c))).toEqual([])
  })

  it('draws the same shapes as BrandMark.vue', () => {
    // Two files, one mark. The favicon's only licensed difference is the
    // `translate(4 4)` that makes room for the plate, so every geometry string
    // is byte-identical and a redraw in one file that is not made in the other
    // fails here rather than shipping two marks that used to be one.
    const mark = read('src/components/BrandMark.vue')
    const geometry = [
      'd="M12 7.6 L4.6 16.4 M12 7.6 L19.4 16.4"',
      'x="7.6" y="0.6" width="8.8" height="8.8" rx="3"',
      'x="0.4" y="14.6" width="8.8" height="8.8" rx="3"',
      'x="14.8" y="14.6" width="8.8" height="8.8" rx="3"',
    ]
    for (const shape of geometry) {
      expect(mark, `BrandMark.vue lost ${shape}`).toContain(shape)
      expect(favicon, `favicon.svg lost ${shape}`).toContain(shape)
    }
  })

  it('is a square viewBox, so no browser crops it', () => {
    const box = /viewBox="0 0 (\d+) (\d+)"/.exec(favicon)
    expect(box, 'favicon.svg has no viewBox').not.toBeNull()
    expect(box![1]).toBe(box![2])
  })
})

describe('index.html and data/brand.ts agree', () => {
  const html = read('index.html')

  it('titles the tab with the product name and nothing else', () => {
    // There is no build-time templating in this file, so the name is written
    // out. This assertion is the only thing between that and two products.
    expect(/<title>([^<]*)<\/title>/.exec(html)?.[1]).toBe(PRODUCT_NAME)
  })

  it('paints the browser chrome with --bg-app’s value, not a stray literal', () => {
    const themeColor = /name="theme-color"\s+content="([^"]+)"/.exec(html)?.[1]
    expect(themeColor).toBe(darkToken('bg-app'))
  })

  it('describes the product rather than a name it used to have', () => {
    const description = /name="description"[\s\S]*?content="([^"]+)"/.exec(html)?.[1] ?? ''
    expect(description.length).toBeGreaterThan(20)
    expect(description).not.toMatch(/Validator Studio|\bM2\b/)
  })
})

describe('the product name is spelled in exactly one place', () => {
  it('is declared in data/brand.ts and read everywhere else', () => {
    const spellings = hits(new RegExp(PRODUCT_NAME))
      .filter((hit) => !hit.startsWith('src/data/brand.ts:'))
    expect(spellings, spellings.join('\n')).toEqual([])
  })

  it('composes a canvas title as “<workflow> · <product>”', () => {
    expect(pageTitle('Idea validator')).toBe(`Idea validator · ${PRODUCT_NAME}`)
    expect(pageTitle(null)).toBe(PRODUCT_NAME)
  })

  it('has retired the M2 kicker from every surface', () => {
    const kickers = hits(/>M2</)
    expect(kickers, kickers.join('\n')).toEqual([])
  })

  it('has no surface still calling itself Validator Studio', () => {
    // U5's grep, and U4's: the old product name must not survive anywhere in
    // `src/`. The last occurrences of it are the two canvases' `<h1>` TEXT,
    // which row U4 owns and W1 rewords into the workflow vocabulary in the same
    // build - W3 was told to leave those lines byte-identical so the two
    // changes would not land on each other. Until that lands this is a
    // coordination signal naming the outstanding line, not a defect in the
    // brand: everything W3 owns is already clear of it.
    const stale = hits(/Validator Studio/)
    expect(stale, stale.join('\n')).toEqual([])
  })
})

describe('BrandMark draws the glyph and says nothing to a screen reader', () => {
  it('renders an svg that is hidden from the accessibility tree', () => {
    const wrapper = mount(BrandMark)
    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)
    expect(svg.attributes('aria-hidden')).toBe('true')
    // `focusable="false"` as well as `aria-hidden`: IE and some older WebKit
    // put an SVG in the tab order regardless, and a decorative glyph that can
    // be focused is a tab stop that announces nothing.
    expect(svg.attributes('focusable')).toBe('false')
  })

  it('takes its size from a prop and defaults to the header’s 20', () => {
    expect(mount(BrandMark).find('svg').attributes('width')).toBe('20')
    const sized = mount(BrandMark, { props: { size: 16 } }).find('svg')
    expect(sized.attributes('width')).toBe('16')
    expect(sized.attributes('height')).toBe('16')
  })

  it('names no colour of its own', () => {
    // Every fill and stroke is a custom property, which is what makes the mark
    // follow the theme at all. A literal here would be a mark with exactly one
    // appearance for ever.
    const source = read('src/components/BrandMark.vue')
    const style = /<style[\s\S]*?<\/style>/.exec(source)?.[0] ?? ''
    expect(style).toMatch(/var\(--on-accent-cyan\)/)
    expect(style).toMatch(/var\(--on-accent-mint\)/)
    expect(style.match(/#[0-9a-fA-F]{3,8}\b|\brgba?\(/g)).toBeNull()
  })
})

describe('BrandLockup is a link on a canvas and a heading on a wall', () => {
  it('renders a.brand-lockup[href="#/"] with an accessible name of its own', () => {
    const wrapper = mount(BrandLockup, { props: { as: 'link' } })
    const link = wrapper.find('a.brand-lockup')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('#/')
    // Not the link's text content, which is the WORKFLOW's name once a view
    // fills the slot. A way home announced as "Idea validator" is worse than
    // no way home.
    expect(link.attributes('aria-label')).toContain(PRODUCT_NAME)
    expect(link.attributes('aria-label')).toMatch(/home/i)
  })

  it('puts the product name in the kicker slot and the view’s heading beside it', () => {
    const wrapper = mount(BrandLockup, {
      props: { as: 'link' },
      slots: { default: '<h1>Idea validator</h1>' },
    })
    expect(wrapper.find('.brand-wordmark').text()).toBe(PRODUCT_NAME)
    expect(wrapper.find('.brand-words h1').text()).toBe('Idea validator')
    // The mark is inside the link and hidden, so the link has one name.
    expect(wrapper.find('a.brand-lockup .brand-mark').attributes('aria-hidden')).toBe('true')
  })

  it('is a static element on the wall, where the product name IS the heading', () => {
    const wrapper = mount(BrandLockup, { props: { as: 'static' } })
    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.find('div.brand-lockup').exists()).toBe(true)
    expect(wrapper.find('h1').text()).toBe(PRODUCT_NAME)
  })

  it('keeps the class names studio.css and the contrast audit read by name', () => {
    // `.brand-lockup` and `.brand-mark` are styled globally and are named in
    // two rows of `scripts/contrast-audit.mjs`. Renaming them here would leave
    // the gate measuring a pairing the page no longer paints.
    for (const as of ['link', 'static'] as const) {
      const wrapper = mount(BrandLockup, { props: { as } })
      expect(wrapper.find('.brand-lockup').exists()).toBe(true)
      expect(wrapper.find('.brand-mark svg').exists()).toBe(true)
    }
  })
})

describe('the four surfaces render the lockup rather than their own copy of it', () => {
  const surfaces = [
    'src/views/StudioView.vue',
    'src/components/builder/BuilderView.vue',
    'src/components/SignInPanel.vue',
    'src/App.vue',
  ]

  it('mounts BrandLockup on all four', () => {
    for (const file of surfaces) {
      expect(read(file), `${file} does not render BrandLockup`).toContain('<BrandLockup')
    }
  })

  it('has no CircleDot placeholder left anywhere', () => {
    const placeholders = hits(/CircleDot/)
    expect(placeholders, placeholders.join('\n')).toEqual([])
  })
})

/**
 * ROUND-2 X2 / §5 ruling 2: the product sentence is one string, and the home is
 * now one of its readers.
 *
 * The defect this closes was not a wrong sentence, it was a MISSING reader.
 * `SignInPanel` said what the product is and the signed-in home said nothing at
 * all, so the only screen that answered "what can I do here" was the one you
 * stop seeing the moment you have an account (AUDIT-R2 H1, and half of the cold
 * read's Q2 failure). The obvious way to fix that is to paste the sentence into
 * `HomeView`, which is two strings that agree today; these three assertions are
 * what make it one string instead - and the last of them fails on that paste
 * rather than waiting for the two to drift.
 */
describe('the product sentence is spelled once and read on both surfaces', () => {
  const readers = ['src/views/HomeView.vue', 'src/components/SignInPanel.vue']

  it('is declared in data/brand.ts', () => {
    expect(PRODUCT_SENTENCE.length).toBeGreaterThan(40)
    expect(read('src/data/brand.ts')).toContain(PRODUCT_SENTENCE.slice(0, 40))
  })

  it('is rendered by the home and by the sign-in wall, from the constant', () => {
    for (const file of readers) {
      const source = read(file)
      expect(source, `${file} does not import PRODUCT_SENTENCE`).toContain('PRODUCT_SENTENCE')
      expect(source, `${file} does not render it`).toContain('{{ PRODUCT_SENTENCE }}')
    }
  })

  it('is written out nowhere but data/brand.ts', () => {
    // The first six words are enough to catch a paste and short enough to
    // survive a later edit to the tail of the sentence.
    const opening = PRODUCT_SENTENCE.split(' ').slice(0, 6).join(' ')
    const spellings = hits(new RegExp(opening.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
      .filter((hit) => !hit.startsWith('src/data/brand.ts:'))
    expect(spellings, spellings.join('\n')).toEqual([])
  })
})
