import { describe, expect, it } from 'vitest'
import { escapeHtml, renderMarkdown, safeHref } from '../src/utils/markdown'

/**
 * The report body is written by the Reporter agent, so it is untrusted input.
 * The first block is the one that matters: it pins the invariant that no
 * sequence of input characters becomes markup. The rendering tests below it
 * are ordinary regression cover.
 */
describe('renderMarkdown security invariant', () => {
  it('escapes raw HTML rather than emitting it', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
    // The attribute survives as inert escaped TEXT, which is correct - what
    // must never appear is an actual tag for the browser to parse.
    expect(html).toBe('<p>&lt;img src=x onerror=alert(1)&gt;</p>')
  })

  it('escapes a script tag split across markdown emphasis', () => {
    const html = renderMarkdown('**<script>**alert(1)**</script>**')
    expect(html).not.toContain('<script')
    expect(html).toContain('&lt;script&gt;')
  })

  it('refuses a javascript: link and renders the source text instead', () => {
    const html = renderMarkdown('[click me](javascript:alert(1))')
    expect(html).not.toContain('<a href')
    expect(html).toContain('click me')
  })

  it('refuses data: and vbscript: links', () => {
    expect(safeHref('data:text/html;base64,PHNjcmlwdD4=')).toBeNull()
    expect(safeHref('vbscript:msgbox(1)')).toBeNull()
    expect(safeHref('JaVaScRiPt:alert(1)')).toBeNull()
  })

  it('refuses a scheme obfuscated with whitespace or control characters', () => {
    expect(safeHref('java\tscript:alert(1)')).toBeNull()
    expect(safeHref('java\nscript:alert(1)')).toBeNull()
    expect(safeHref(' javascript:alert(1) '.replace(' ', '\u0000'))).toBeNull()
  })

  it('refuses a protocol-relative //host URL', () => {
    // No colon and a leading slash, so it slipped the "relative links are
    // inert" clause while resolving cross-origin against the page's scheme.
    expect(safeHref('//evil.example/pwn')).toBeNull()
    const html = renderMarkdown('[x](//evil.example/pwn)')
    expect(html).not.toContain('<a href')
    expect(html).toContain('x')
  })

  it('still admits a single-slash path, which is same-origin', () => {
    expect(safeHref('/local/path')).toBe('/local/path')
    expect(safeHref('./sibling')).toBe('./sibling')
    expect(safeHref('#anchor')).toBe('#anchor')
    // WHATWG resolves a leading backslash pair same-origin, so it is not the
    // protocol-relative case and does not need refusing.
    expect(safeHref('/\evil.example/pwn')).toBe('/\evil.example/pwn')
  })

  it('survives pathological blockquote nesting instead of throwing', () => {
    // Unbounded recursion threw RangeError out of a Vue computed, blanking the
    // report panel. Past the cap the text degrades to escaped paragraphs.
    const deep = '>'.repeat(20000) + ' still here'
    let html = ''
    expect(() => { html = renderMarkdown(deep) }).not.toThrow()
    expect(html).toContain('still here')
  })

  it('cannot be tricked into re-forming a colon through entities', () => {
    // The href is escaped before safeHref sees it, so `&#58;` stays literal.
    const html = renderMarkdown('[x](javascript&#58;alert(1))')
    expect(html).not.toContain('<a href="javascript')
  })

  it('admits ordinary http(s) URLs, including hyphens and query strings', () => {
    expect(safeHref('https://news.ycombinator.com/item?id=1-2_3')).toBe(
      'https://news.ycombinator.com/item?id=1-2_3',
    )
    expect(safeHref('http://example.com/a-b-c')).toBe('http://example.com/a-b-c')
  })

  it('adds rel=noopener to every emitted link', () => {
    const html = renderMarkdown('[HN](https://news.ycombinator.com/item?id=1)')
    expect(html).toContain('rel="noopener noreferrer nofollow"')
    expect(html).toContain('target="_blank"')
  })

  it('strips control characters so the code-span sentinel cannot be forged', () => {
    const forged = renderMarkdown('\u0000CODE0\u0000 and `real`')
    expect(forged).toContain('<code>real</code>')
    // The injected sentinel was stripped, so it never resolved to a code span.
    expect(forged).not.toContain('<code>CODE0</code>')
    expect(escapeHtml('a\u0000b\u001fc')).toBe('abc')
  })
})

describe('renderMarkdown rendering', () => {
  it('renders ATX headings at the right level', () => {
    expect(renderMarkdown('# Verdict')).toBe('<h1>Verdict</h1>')
    expect(renderMarkdown('### Demand')).toBe('<h3>Demand</h3>')
  })

  it('renders unordered and ordered lists', () => {
    expect(renderMarkdown('- one\n- two')).toBe('<ul><li>one</li><li>two</li></ul>')
    expect(renderMarkdown('1. first\n2. second')).toBe('<ol><li>first</li><li>second</li></ol>')
  })

  it('renders a pipe table, which is how the score breakdown arrives', () => {
    const html = renderMarkdown('| Dim | Score |\n| --- | --- |\n| Demand | 3 |')
    expect(html).toContain('<th>Dim</th>')
    expect(html).toContain('<td>Demand</td>')
    expect(html).toContain('<td>3</td>')
  })

  it('renders emphasis, strong and inline code', () => {
    const html = renderMarkdown('**bold** and *em* and `code`')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<em>em</em>')
    expect(html).toContain('<code>code</code>')
  })

  it('does not interpret markdown inside a code span', () => {
    expect(renderMarkdown('`**not bold**`')).toContain('<code>**not bold**</code>')
  })

  it('renders a fenced code block and keeps its content verbatim', () => {
    const html = renderMarkdown('```json\n{"a": 1}\n```')
    expect(html).toContain('<pre><code class="language-json">')
    expect(html).toContain('{&quot;a&quot;: 1}')
  })

  it('renders a blockquote without double-escaping its contents', () => {
    const html = renderMarkdown('> a & b')
    expect(html).toContain('<blockquote>')
    expect(html).toContain('a &amp; b')
    expect(html).not.toContain('&amp;amp;')
  })

  it('linkifies a bare URL without swallowing trailing punctuation', () => {
    const html = renderMarkdown('See https://example.com/page, then stop.')
    expect(html).toContain('href="https://example.com/page"')
    expect(html).toContain(', then stop.')
  })

  it('returns an empty string for empty input rather than throwing', () => {
    expect(renderMarkdown('')).toBe('')
  })

  it('degrades unknown syntax to an escaped paragraph', () => {
    expect(renderMarkdown('just some prose')).toBe('<p>just some prose</p>')
  })
})
