/**
 * A deliberately small Markdown subset renderer for the validation report.
 *
 * WHY NOT `marked` + `dompurify`: the body rendered here is written by the
 * Reporter agent - it is model output, not repository content - so it is
 * untrusted by construction. A sanitiser is a denylist applied *after* markup
 * exists. This is the opposite order and is the reason it can be reasoned
 * about in one sitting:
 *
 *   1. Every character of input is HTML-escaped FIRST (`escapeHtml`).
 *   2. Only then is structure recognised, and every tag emitted is a literal
 *      in this file.
 *   3. The one place an attacker-influenced value lands inside a tag is a link
 *      `href`, and `safeHref` admits only `http:` / `https:`.
 *
 * So there is no path by which input text becomes markup. That property is
 * what `markdown.spec.ts` pins, not the prettiness of the output.
 *
 * The supported subset is exactly what `config/tasks.yaml` asks the Reporter
 * for: ATX headings, unordered and ordered lists, blockquotes, fenced code,
 * pipe tables, thematic breaks, paragraphs, and inline emphasis / code /
 * links. Anything else degrades to an escaped paragraph rather than throwing,
 * because a report that renders imperfectly beats a report that renders not at
 * all - which is the defect this file exists to fix.
 */

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

/**
 * Control characters are stripped, not escaped. They render as nothing, they
 * are never legitimate in a report body, and removing them here means the
 * `SENTINEL` used for code spans below cannot be forged by the input.
 */
export function escapeHtml(value: string): string {
  return value
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
    .replace(/[&<>"']/g, (char) => ESCAPES[char])
}

/** Not producible by `escapeHtml`, so a code-span placeholder cannot be spoofed. */
const SENTINEL = '\u0000'

/**
 * `http:` and `https:` only. A relative URL is admitted because the Reporter
 * cites absolute source URLs and anything relative is inert anyway; every
 * other scheme - `javascript:`, `data:`, `vbscript:`, and the whitespace- and
 * entity-obfuscated spellings of them - returns null and the caller renders
 * the link as plain text instead.
 *
 * The href arrives already escaped, so `&#58;` and friends cannot re-form a
 * colon after this check: escaping happens before parsing, never after.
 */
export function safeHref(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed || /[\u0000-\u001f\u007f]/.test(trimmed)) return null
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  // A protocol-relative `//host/path` carries no colon and starts with `/`, so
  // it slipped through the relative-link clause below while being nothing of
  // the sort: the browser resolves it against the page's scheme and navigates
  // off-site. Model-authored text must not be able to produce a one-click
  // cross-origin link, so it is refused before that clause can see it.
  if (/^\/\//.test(trimmed)) return null
  // Relative and anchor links carry no scheme and cannot execute. A single
  // leading slash is same-origin by WHATWG resolution, backslashes included.
  if (/^[./#?]/.test(trimmed) && !trimmed.includes(':')) return trimmed
  return null
}

/** Inline spans, applied to text that is ALREADY html-escaped. */
function renderInline(escaped: string): string {
  let out = escaped

  // Code spans first: their contents must not be re-interpreted as emphasis.
  const codeSpans: string[] = []
  out = out.replace(/`([^`]+)`/g, (_match, code: string) => {
    codeSpans.push(code)
    return `${SENTINEL}CODE${codeSpans.length - 1}${SENTINEL}`
  })

  // [label](href) - the href is validated, the label stays escaped text.
  out = out.replace(/\[([^\]]*)\]\(([^)\s]+)\)/g, (match, label: string, href: string) => {
    const safe = safeHref(href)
    if (!safe) return match
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer nofollow">${label || safe}</a>`
  })

  // Bare URLs the Reporter emits without link syntax.
  out = out.replace(/(^|[\s(])((?:https?:\/\/)[^\s<>()]+[^\s<>().,;:!?])/g, (_m, lead: string, url: string) => {
    const safe = safeHref(url)
    if (!safe) return `${lead}${url}`
    return `${lead}<a href="${safe}" target="_blank" rel="noopener noreferrer nofollow">${url}</a>`
  })

  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
  out = out.replace(/~~([^~]+)~~/g, '<del>$1</del>')

  out = out.replace(/\u0000CODE(\d+)\u0000/g, (_m, index: string) => `<code>${codeSpans[Number(index)]}</code>`)
  return out
}

function renderTable(rows: string[]): string {
  const cells = (row: string): string[] =>
    row
      .replace(/^\s*\|/, '')
      .replace(/\|\s*$/, '')
      .split('|')
      .map((cell) => cell.trim())

  const header = cells(rows[0])
  const body = rows.slice(2).map(cells)
  const head = `<thead><tr>${header.map((c) => `<th>${renderInline(c)}</th>`).join('')}</tr></thead>`
  const rest = body
    .map((row) => `<tr>${row.map((c) => `<td>${renderInline(c)}</td>`).join('')}</tr>`)
    .join('')
  return `<table>${head}<tbody>${rest}</tbody></table>`
}

const TABLE_DIVIDER = /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/

/**
 * Blockquotes recurse one level per `>`, and a Vue computed that throws blanks
 * the panel. A body with thousands of nested quote markers is implausible from
 * the Reporter, but "implausible" is not a bound: past the cap the remaining
 * text renders as escaped paragraphs, which is ugly and readable rather than
 * absent.
 */
const MAX_BLOCKQUOTE_DEPTH = 16

export function renderMarkdown(source: string, depth = 0): string {
  if (!source) return ''
  // Escape once, up front. Everything below operates on safe text.
  const lines = escapeHtml(source.replace(/\r\n?/g, '\n')).split('\n')
  const html: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    // Fenced code. The fence content is emitted verbatim (already escaped).
    const fence = line.match(/^\s*(?:```|~~~)(.*)$/)
    if (fence) {
      const language = fence[1].trim().replace(/[^a-zA-Z0-9_-]/g, '')
      const buffer: string[] = []
      index += 1
      while (index < lines.length && !/^\s*(?:```|~~~)\s*$/.test(lines[index])) {
        buffer.push(lines[index])
        index += 1
      }
      index += 1
      const attr = language ? ` class="language-${language}"` : ''
      html.push(`<pre><code${attr}>${buffer.join('\n')}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length
      html.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`)
      index += 1
      continue
    }

    if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) {
      html.push('<hr />')
      index += 1
      continue
    }

    // Pipe table: a header row followed by a divider row.
    if (line.includes('|') && index + 1 < lines.length && TABLE_DIVIDER.test(lines[index + 1])) {
      const rows: string[] = []
      while (index < lines.length && lines[index].includes('|')) {
        rows.push(lines[index])
        index += 1
      }
      html.push(renderTable(rows))
      continue
    }

    // `>` was escaped to `&gt;` on entry, so the marker is matched in its
    // escaped spelling. Escaping first is the invariant; this is its cost.
    if (/^\s*&gt;\s?/.test(line)) {
      const buffer: string[] = []
      while (index < lines.length && /^\s*&gt;\s?/.test(lines[index])) {
        buffer.push(lines[index].replace(/^\s*&gt;\s?/, ''))
        index += 1
      }
      const inner =
        depth >= MAX_BLOCKQUOTE_DEPTH
          ? `<p>${renderInline(buffer.join(' '))}</p>`
          : renderMarkdown(unescapeForNesting(buffer.join('\n')), depth + 1)
      html.push(`<blockquote>${inner}</blockquote>`)
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/
    const ordered = /^\s*\d+[.)]\s+(.*)$/
    if (bullet.test(line) || ordered.test(line)) {
      const isOrdered = ordered.test(line)
      const pattern = isOrdered ? ordered : bullet
      const items: string[] = []
      while (index < lines.length && pattern.test(lines[index])) {
        items.push(lines[index].match(pattern)![1])
        index += 1
      }
      const tag = isOrdered ? 'ol' : 'ul'
      html.push(`<${tag}>${items.map((item) => `<li>${renderInline(item)}</li>`).join('')}</${tag}>`)
      continue
    }

    // Paragraph: consume until a blank line or a line that starts a new block.
    const buffer: string[] = []
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      buffer.push(lines[index].trim())
      index += 1
    }
    if (buffer.length) html.push(`<p>${renderInline(buffer.join(' '))}</p>`)
    else index += 1
  }

  return html.join('\n')
}

function isBlockStart(line: string): boolean {
  return (
    /^(#{1,6})\s+/.test(line) ||
    /^\s*(?:```|~~~)/.test(line) ||
    /^\s*&gt;\s?/.test(line) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    /^\s*(?:[-*_]\s*){3,}$/.test(line)
  )
}

/**
 * Blockquotes recurse, and `renderMarkdown` escapes on entry - so nested text
 * would be escaped twice and render as visible `&amp;lt;`. Undoing the escape
 * immediately before re-entry keeps the single-escape invariant intact: the
 * text is escaped exactly once, by the innermost call.
 */
function unescapeForNesting(escaped: string): string {
  return escaped
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
}
