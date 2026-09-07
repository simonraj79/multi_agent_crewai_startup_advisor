import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportPanel from '../src/components/ReportPanel.vue'
import { renderMarkdown } from '../src/utils/markdown'

/**
 * Audit L3, both halves. Neither was reachable when it was written, and both
 * were single-fact defences living in another file:
 *
 *  - `ReportPanel.vue` bound `:href="source.url"` straight through, relying on
 *    the server validating `Evidence.url` to http(s). One schema edit away.
 *  - `renderInline` ran the emphasis passes over text that already contained
 *    emitted anchors, so `*` inside a href was rewritten into the attribute.
 *    Inert only because `escapeHtml` runs first and no quote can close the
 *    attribute.
 */

function mountWithSources(sources: Array<{ url?: string | null; title?: string | null }>) {
  return mount(ReportPanel, {
    props: {
      report: { markdown_body: '# Verdict', sources },
      verdict: null,
      open: true,
    },
  })
}

describe('L3: a citation href goes through safeHref', () => {
  it('renders an https citation as a link', () => {
    const wrapper = mountWithSources([{ url: 'https://example.com/a', title: 'A' }])
    const anchor = wrapper.find('.report-sources a')
    expect(anchor.exists()).toBe(true)
    expect(anchor.attributes('href')).toBe('https://example.com/a')
    expect(anchor.attributes('rel')).toBe('noopener noreferrer nofollow')
  })

  it('renders a javascript: citation as inert text, with no anchor at all', () => {
    const wrapper = mountWithSources([{ url: 'javascript:alert(1)', title: 'Trust me' }])
    expect(wrapper.find('.report-sources a').exists()).toBe(false)
    // Not dropped: losing a citation silently is worse than showing an inert
    // one, so the title still reaches the reader.
    expect(wrapper.find('.report-sources li').text()).toContain('Trust me')
  })

  it('refuses data:, vbscript: and a protocol-relative host the same way', () => {
    for (const url of ['data:text/html;base64,PHNjcmlwdD4=', 'vbscript:msgbox(1)', '//evil.example/pwn']) {
      const wrapper = mountWithSources([{ url, title: null }])
      expect(wrapper.find('.report-sources a').exists(), url).toBe(false)
      // With no title the URL itself is shown, escaped by Vue's interpolation.
      expect(wrapper.find('.report-sources li').text()).toContain(url)
    }
  })

  it('still shows a titleless source with no URL at all', () => {
    const wrapper = mountWithSources([{ url: null, title: null }])
    expect(wrapper.find('.report-sources a').exists()).toBe(false)
    expect(wrapper.find('.report-sources li').text()).toBe('Untitled source')
  })
})

describe('L3: emphasis never rewrites inside an emitted tag', () => {
  it('leaves a * inside a link href alone', () => {
    const html = renderMarkdown('[c](http://x/*a*b)')
    expect(html).toContain('href="http://x/*a*b"')
    // The rewrite it used to do, spelled out so the test names the defect.
    expect(html).not.toContain('href="http://x/<em>a</em>b"')
  })

  it('leaves a * inside a BARE url alone, in the href and in the visible text', () => {
    const html = renderMarkdown('see http://x.com/*a*b now')
    expect(html).toContain('href="http://x.com/*a*b"')
    expect(html).toContain('>http://x.com/*a*b<')
    expect(html).not.toContain('<em>')
  })

  it('leaves a ** inside a link href alone', () => {
    const html = renderMarkdown('[c](http://x/**a**b)')
    expect(html).toContain('href="http://x/**a**b"')
    expect(html).not.toContain('<strong>')
  })

  it('leaves a ~~ inside a link href alone', () => {
    const html = renderMarkdown('[c](http://x/~~a~~b)')
    expect(html).toContain('href="http://x/~~a~~b"')
    expect(html).not.toContain('<del>')
  })

  it('still renders a code span inside a link label', () => {
    const html = renderMarkdown('[`co`de](http://x)')
    expect(html).toBe(
      '<p><a href="http://x" target="_blank" rel="noopener noreferrer nofollow"><code>co</code>de</a></p>',
    )
  })

  it('still emphasises ACROSS a link, which is the case holding the whole anchor would break', () => {
    const html = renderMarkdown('a **b [c](http://x.com) d** e')
    expect(html).toContain('<strong>b <a href="http://x.com"')
    expect(html).toContain('</a> d</strong>')
  })

  it('still emphasises INSIDE a link label', () => {
    const html = renderMarkdown('[**b**](http://x)')
    expect(html).toContain('<strong>b</strong></a>')
  })

  it('leaves no sentinel on screen', () => {
    const html = renderMarkdown('a `c` and [**l**](http://x/*p*) and http://y.com/*q*')
    expect(html).not.toContain('\u0000')
    expect(html).not.toMatch(/H\d+/)
  })
})
