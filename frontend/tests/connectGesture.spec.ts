import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import BuilderNode from '../src/components/builder/BuilderNode.vue'
import { useBuilderCanvas } from '../src/composables/useBuilderCanvas'
import { NODE_KINDS, outPortsOf } from '../src/data/nodeKinds'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import type { BuilderNodeData } from '../src/composables/useBuilderCanvas'
import type { BuilderDocument, NodeId } from '../src/types/builder'

/**
 * A gesture that starts must be able to end, and a key that is documented must
 * reach a handler.
 *
 * `E` (section 4.1) armed the MOUSE's connect gesture and then handed the
 * author nothing to finish it with: `connectDrag` is cleared only by
 * `onConnectEnd`, which a pointer fires, so a keyboard-started connect survived
 * Escape, every click and any amount of waiting. Measured in Chromium: the
 * container kept `.is-connecting` with two `builder-port-ready` animations
 * running on an idle canvas - which section 5.5 forbids outright - and, worse,
 * `escape()` stayed pinned on its first rung, so Escape could never clear a
 * selection again for the rest of the session.
 *
 * Underneath that sat a second defect with a wider blast radius, and it is the
 * one this file guards hardest. `BuilderNode`'s title carried `tabindex="-1"`,
 * which in Chromium makes an element MOUSE-focusable, plus
 * `@keydown.esc.stop.prevent` and `@keydown.enter.prevent` - modifiers that
 * fire unconditionally. So clicking ANY node card focused its `<strong>`, and
 * from that moment Escape was `stopPropagation`d before the window listener saw
 * it and Enter arrived already `defaultPrevented`, which `useBuilderHotkeys`
 * skips by design. The Escape ladder and every Enter binding were dead, and no
 * jsdom mount could see it because none of them clicks a card and then presses
 * a key at the window.
 */

const document_ = (): BuilderDocument => documentFromTemplate(MINIMAL_GATED_AGENT)

function harness() {
  const doc = ref<BuilderDocument>(document_())
  const commits: string[] = []
  const canvas = useBuilderCanvas({
    document: {
      doc,
      addNode: () => {},
      addEdge: (origin, target) => {
        commits.push(`${origin.source}:${origin.source_port}->${target}`)
        doc.value = {
          ...doc.value,
          edges: [
            ...doc.value.edges,
            {
              id: `e${doc.value.edges.length + 1}` as never,
              source: origin.source,
              source_port: origin.source_port,
              target,
              target_port: 'in',
            },
          ],
        }
      },
      moveNodes: () => {},
      deleteSelection: () => {},
      setEdgePort: () => {},
      retargetEdge: () => {},
      setJoin: () => {},
    },
  })
  return { doc, canvas, commits }
}

/** The gate, which is the node an author most often links from by keyboard. */
const gateId = (doc: BuilderDocument): NodeId =>
  doc.nodes.find((node) => node.kind === 'gate')!.id

describe('a keyboard link has a beginning, a middle and an end', () => {
  it('numbers only the targets an edge could legally reach', () => {
    const { doc, canvas } = harness()
    const count = canvas.beginLink(gateId(doc.value))

    expect(count).toBeGreaterThan(0)
    const numbered = canvas.nodes.value.filter((node) => node.data.linkIndex != null)
    expect(numbered).toHaveLength(count)
    // The input node renders no inbound port at all (section 5.3), so it is a
    // parse refusal and never a candidate - the keyboard must not be the softer
    // door than the mouse.
    expect(numbered.map((node) => node.data.node.kind)).not.toContain('input')
    // Exactly one is current, and it is the one Enter would take.
    expect(canvas.nodes.value.filter((node) => node.data.linkCurrent)).toHaveLength(1)
  })

  it('refuses to start a gesture that has no possible ending', () => {
    const { doc, canvas } = harness()
    const output = doc.value.nodes.find((node) => node.kind === 'output')!

    // `output` offers no source port at all, so there is nothing to link FROM.
    expect(outPortsOf(output)).toEqual([])
    expect(canvas.beginLink(output.id)).toBe(0)
    expect(canvas.linkMode.value).toBeNull()
    expect(canvas.connectDrag.value).toBeNull()
  })

  it('cycles the candidates with Tab and commits exactly one edge with Enter', () => {
    const { doc, canvas, commits } = harness()
    const source = gateId(doc.value)
    const total = canvas.beginLink(source)
    const first = canvas.linkMode.value!.candidates[0]

    canvas.cycleLink(1)
    expect(canvas.linkMode.value!.index).toBe(1 % total)
    canvas.cycleLink(-1)
    expect(canvas.linkMode.value!.candidates[canvas.linkMode.value!.index]).toBe(first)

    canvas.commitLink()

    expect(commits).toHaveLength(1)
    expect(commits[0]).toBe(`${source}:${outPortsOf(doc.value.nodes.find((n) => n.id === source)!)[0]}->${first}`)
    // And the gesture is over: nothing animates, nothing is numbered.
    expect(canvas.linkMode.value).toBeNull()
    expect(canvas.connectDrag.value).toBeNull()
  })

  it('aborts through cancelConnect with zero commits and zero live state', () => {
    const { doc, canvas, commits } = harness()
    canvas.beginLink(gateId(doc.value))
    expect(canvas.connectDrag.value).not.toBeNull()

    canvas.cancelConnect()

    // All three refs, which is the whole repair: `cancelPortMenu` cleared one of
    // them, so the container stayed `.is-connecting` after Escape.
    expect(canvas.connectDrag.value).toBeNull()
    expect(canvas.linkMode.value).toBeNull()
    expect(canvas.portMenuRequest.value).toBeNull()
    expect(commits).toEqual([])
    expect(canvas.nodes.value.every((node) => node.data.linkIndex == null)).toBe(true)
  })
})

describe('the node filter dims rather than hides, and matches on both names', () => {
  it('marks matches and dims the rest once a query is typed', () => {
    const { canvas } = harness()
    expect(canvas.nodes.value.every((node) => !node.data.filterDimmed)).toBe(true)

    canvas.filterQuery.value = 'draft'

    const matched = canvas.nodes.value.filter((node) => node.data.filterMatch)
    const dimmed = canvas.nodes.value.filter((node) => node.data.filterDimmed)
    expect(matched.length).toBeGreaterThan(0)
    expect(dimmed.length).toBeGreaterThan(0)
    // Nothing is removed: the shape of the graph an author is searching inside
    // has to survive the search.
    expect(matched.length + dimmed.length).toBe(canvas.nodes.value.length)
  })

  it('filters nothing at all for an empty or whitespace query', () => {
    const { canvas } = harness()
    canvas.filterQuery.value = '   '
    expect(canvas.nodes.value.some((node) => node.data.filterDimmed)).toBe(false)
  })
})

describe('R reaches the card that owns the rename', () => {
  it('latches a request the card can see, and clears it once the caret is there', () => {
    const { doc, canvas } = harness()
    const target = doc.value.nodes[0].id

    canvas.requestRename(target)
    expect(canvas.nodes.value.find((node) => node.id === target)!.data.renaming).toBe(true)

    canvas.noteRenameStarted()
    expect(canvas.nodes.value.every((node) => !node.data.renaming)).toBe(true)
  })
})

describe('a node title that is not being edited consumes no keys', () => {
  const dataFor = (overrides: Partial<BuilderNodeData> = {}): BuilderNodeData => {
    const node = documentFromTemplate(MINIMAL_GATED_AGENT).nodes.find((n) => n.kind === 'agent')!
    return {
      node,
      index: 3,
      ports: outPortsOf(node),
      acceptsIncoming: NODE_KINDS[node.kind].acceptsIncoming,
      problems: [],
      severity: null,
      joined: false,
      anchor: false,
      loopTarget: false,
      loopIllegal: false,
      connectable: false,
      flashing: false,
      inbound: 0,
      landing: false,
      ...overrides,
    }
  }

  // Attached to the document on purpose: the whole subject here is whether a
  // key gets from the title to the WINDOW listener, and a detached mount has no
  // path to one.
  const mountCard = (data: BuilderNodeData) =>
    mount(BuilderNode, {
      props: { id: data.node.id, data },
      global: { stubs: { Handle: true } },
      attachTo: document.body,
    })

  it('is not a focus target at all until it is being edited', () => {
    const wrapper = mountCard(dataFor())
    // `tabindex="-1"` is mouse-focusable in Chromium, which is how a click on a
    // card put focus inside the title and made every window binding unreachable.
    expect(wrapper.get('.builder-title').attributes('tabindex')).toBeUndefined()
  })

  it('lets Escape and Enter travel on to the window listener', async () => {
    const wrapper = mountCard(dataFor())
    const title = wrapper.get('.builder-title')

    for (const key of ['Escape', 'Enter']) {
      const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
      let reachedWindow = false
      const probe = () => {
        reachedWindow = true
      }
      window.addEventListener('keydown', probe)
      title.element.dispatchEvent(event)
      window.removeEventListener('keydown', probe)

      expect(reachedWindow, `${key} was stopped by a title that is not being edited`).toBe(true)
      expect(event.defaultPrevented, `${key} arrived already prevented`).toBe(false)
    }
  })

  it('still consumes both keys once the caret is in the label', async () => {
    const wrapper = mountCard(dataFor({ renaming: true }))
    await wrapper.vm.$nextTick()
    const title = wrapper.get('.builder-title')
    expect(title.attributes('contenteditable')).toBe('true')

    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    title.element.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(true)
    // And the card told the canvas its latch may be cleared.
    expect(wrapper.emitted('rename-started')).toBeTruthy()
  })
})
