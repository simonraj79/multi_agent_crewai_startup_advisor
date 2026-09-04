import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { h, shallowRef } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { BUILDER_PROBLEMS, useBuilderProblems } from '../src/composables/useBuilderProblems'
import ProblemsPanel from '../src/components/builder/ProblemsPanel.vue'
import FieldProblem from '../src/components/builder/fields/FieldProblem.vue'
import { FIELD_CODES, PROBLEM_CODES } from '../src/types/builder'
import type { BuilderProblem, ProblemCode } from '../src/types/builder'

/**
 * No problem the server reports is ever silently dropped.
 *
 * That is the whole subject. A message `bounds.py` wrote and no surface renders
 * is worse than no check at all: the author cannot publish, the button says why
 * in a count, and the sentence that would tell them what to change exists only
 * in a network response. The index has three sinks - the document group, the
 * per-field bucket, and the node's unplaced strip - and this file asserts the
 * partition is TOTAL over every code in `PROBLEM_CODES`, in all four anchoring
 * shapes a problem can arrive in.
 *
 * The dual-anchor rule is asserted against the Python rather than restated: a
 * client-side table of "which codes carry both anchors" would be a mirror that
 * can rot un-noticed, which is how this repo's own counts went wrong five
 * times.
 */

/**
 * The path goes through a parameter, and that is not a style choice.
 *
 * Vite recognises `new URL('<string literal>', import.meta.url)` as an ASSET
 * reference and rewrites it to a served `http://localhost:3000/@fs/...` URL, so
 * an inlined literal here reaches `fileURLToPath` as an http URL and fails with
 * `The URL must be of scheme file` - at import time, taking the whole file down
 * with zero tests run. A variable is not statically analysable, so the
 * expression survives to runtime as the file URL it is. `nodeKinds.spec.ts` and
 * `builderTypes.spec.ts` both route through a helper for the same reason.
 */
function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

const BOUNDS_PY = pythonSource('../../src/brief_crew/builder/bounds.py')

/**
 * Which anchors `bounds.py` sets alongside each `code=`.
 *
 * Sliced from one `code=` to the next rather than parsed: the constructor calls
 * are `Problem(...)` literals with nested conditionals and f-strings in them, so
 * matching balanced parentheses with a regex is the fragile option. Every
 * `Problem(` in that file assigns `code=` first and its anchors after, so the
 * slice between two `code=` markers contains exactly one problem's keywords.
 */
function pythonAnchors(): Map<string, { node: boolean; edge: boolean }> {
  const constants = new Map<string, string>()
  for (const row of BOUNDS_PY.matchAll(/^([A-Z][A-Z0-9_]*) = "([a-z-]+)"$/gm)) {
    constants.set(row[1], row[2])
  }

  const anchors = new Map<string, { node: boolean; edge: boolean }>()
  // Lowercase `code=code` is matched too, and it matters: it is the shared
  // helper that raises the duplicate-id pair, and it has to act as a SLICE
  // BOUNDARY even though it names no constant. Without it the escalation-count
  // slice ran on into that helper and inherited its `edge_id=`, reporting a
  // graph-wide count as a relationship code.
  const markers = [...BOUNDS_PY.matchAll(/code=([A-Za-z_][A-Za-z0-9_]*)/g)]
  markers.forEach((marker, index) => {
    const code = constants.get(marker[1])
    if (!code) return
    const start = marker.index ?? 0
    const end = markers[index + 1]?.index ?? BOUNDS_PY.length
    const body = BOUNDS_PY.slice(start, end)
    const found = anchors.get(code) ?? { node: false, edge: false }
    // `node_id=None` is written nowhere in that file - an anchor is either
    // assigned or the keyword is absent - so presence of the keyword is the
    // fact, except for the one conditional pair which assigns both names.
    found.node = found.node || /\bnode_id=/.test(body)
    found.edge = found.edge || /\bedge_id=/.test(body)
    anchors.set(code, found)
    return
  })
  return anchors
}

const problem = (
  code: string,
  overrides: Partial<BuilderProblem> = {},
): BuilderProblem => ({
  code,
  severity: 'error',
  message: `the server's sentence about ${code}`,
  node_id: null,
  edge_id: null,
  ...overrides,
})

function indexOf(problems: BuilderProblem[]) {
  return useBuilderProblems(shallowRef(problems))
}

describe('a problem is indexed under every anchor it carries, not one of them', () => {
  it('agrees with bounds.py about which codes describe a relationship', () => {
    const anchors = pythonAnchors()
    const both = [...anchors.entries()]
      .filter(([, found]) => found.node && found.edge)
      .map(([code]) => code)
      .sort()

    // SIX, and each is a fact about a PAIR - which is exactly why both maps get
    // an entry: an author looking at either end has to see it.
    //
    // The first three are the originals: an edge naming a port its source does
    // not have, an edge arriving at a kind that accepts none, and a back edge
    // whose source is not a routing kind. The last three arrived with
    // 03-node-library.md D2's edge classes on 2026-09-04, and every one of them
    // is a pair by construction - an `attach` or `member` edge is legal or not
    // according to what is at BOTH of its ends, never according to one.
    expect(both).toEqual([
      'attach-target-not-agent',
      // 09: an attachment whose reference did not survive an export. It is a
      // fact about the pair, like the others here - which node lost its
      // reference, and which edge hung it on an agent.
      'attachment-reference-missing',
      'back-edge-not-router',
      'edge-target-refuses-incoming',
      'edge-unknown-port',
      'member-agent-has-flow-edges',
      'member-target-not-crew',
    ])
    // A sanity check on the scan itself, because a regex that matched nothing
    // would satisfy the assertion above by accident: it has to have found the
    // graph-wide codes too, and found them anchored to at most a node.
    expect(anchors.has('node-count')).toBe(true)
    expect(anchors.get('escalation-count')).toEqual({ node: true, edge: false })
  })

  it('puts a both-anchored problem in the node map and the edge map', () => {
    const index = indexOf([
      problem('edge-unknown-port', { node_id: 'gate_1', edge_id: 'e3' }),
    ])

    expect(index.problemsForNode('gate_1')).toHaveLength(1)
    expect(index.problemsForEdge('e3')).toHaveLength(1)
    expect(index.problemsForNode('gate_1')[0]).toBe(index.problemsForEdge('e3')[0])
    expect(index.documentProblems.value).toEqual([])
  })

  it('leaves an unanchored problem out of both maps and in the document group', () => {
    const index = indexOf([problem('billable-count')])

    expect(index.problemsByNode.value.size).toBe(0)
    expect(index.problemsByEdge.value.size).toBe(0)
    expect(index.documentProblems.value.map((entry) => entry.code)).toEqual(['billable-count'])
  })
})

describe('every code the server can send reaches at least one surface', () => {
  /**
   * The four shapes a problem can arrive in, and the coverage assertion over
   * all of them.
   *
   * Anchors are varied rather than looked up because the claim being tested is
   * that the sinks PARTITION the list, whatever the anchors are. A test that
   * used each code's real anchor would prove the same thing about one shape and
   * miss the case where the server grows an anchor on a code that had none -
   * which is the shape a new check most often arrives in.
   */
  const shapes: Array<{ name: string; node: string | null; edge: string | null }> = [
    { name: 'unanchored', node: null, edge: null },
    { name: 'node-anchored', node: 'agent_1', edge: null },
    { name: 'edge-anchored', node: null, edge: 'e1' },
    { name: 'both-anchored', node: 'agent_1', edge: 'e1' },
  ]

  const everyProblem: BuilderProblem[] = PROBLEM_CODES.flatMap((code) =>
    shapes.map((shape) =>
      problem(code, {
        node_id: shape.node,
        edge_id: shape.edge,
        message: `${code} / ${shape.name}`,
      }),
    ),
  )

  it('renders all of them, with nothing left over and nothing invented', () => {
    const index = indexOf(everyProblem)

    const rendered = new Set<BuilderProblem>()
    for (const entry of index.documentProblems.value) rendered.add(entry)
    for (const [nodeId, bucket] of index.problemsByNode.value) {
      // Exactly what the inspector does: place what `FIELD_CODES` can place,
      // and pin the rest to the node's own strip.
      const placed = bucket.filter((entry) => index.fieldForCode(entry.code) !== undefined)
      for (const entry of placed) {
        const field = index.fieldForCode(entry.code) as string
        expect(index.problemsForField(nodeId, field)).toContain(entry)
        rendered.add(entry)
      }
      for (const entry of index.unplacedForNode(nodeId)) rendered.add(entry)
    }
    for (const [, bucket] of index.problemsByEdge.value) {
      for (const entry of bucket) rendered.add(entry)
    }

    expect(rendered.size).toBe(everyProblem.length)
    expect([...rendered].every((entry) => everyProblem.includes(entry))).toBe(true)
  })

  it('counts every code exactly once as an error or a warning', () => {
    const index = indexOf(everyProblem)
    expect(index.errorCount.value + index.warningCount.value).toBe(everyProblem.length)
  })
})

describe('FIELD_CODES places a problem at the control that caused it', () => {
  it('routes each mapped code to its own field and to no other', () => {
    const mapped = Object.entries(FIELD_CODES) as Array<[ProblemCode, string]>
    expect(mapped.length).toBeGreaterThan(0)

    for (const [code, field] of mapped) {
      const index = indexOf([problem(code, { node_id: 'agent_1' })])
      expect(index.problemsForField('agent_1', field).map((entry) => entry.code)).toEqual([code])
      expect(index.problemsForField('agent_1', 'some_other_field')).toEqual([])
      expect(index.unplacedForNode('agent_1')).toEqual([])
    }
  })

  it('pins an unmapped code to the node strip rather than dropping it', () => {
    const index = indexOf([problem('node-unreachable', { node_id: 'agent_1' })])

    expect(index.fieldForCode('node-unreachable')).toBeUndefined()
    expect(index.unplacedForNode('agent_1').map((entry) => entry.code)).toEqual([
      'node-unreachable',
    ])
  })

  it('pins a mapped code whose control this form does not render', () => {
    // `library-unknown-id` maps to `agent_id`, and `compiler.py` raises it for a
    // CREW's unregistered `crew_id` too. A crew inspector has no `agent_id`
    // control, so without `knownFields` the message would anchor to a field
    // that is not on screen - which is a drop wearing a mapping.
    const index = indexOf([problem('library-unknown-id', { node_id: 'crew_1' })])

    expect(index.unplacedForNode('crew_1', ['crew_id', 'tier'])).toHaveLength(1)
    expect(index.unplacedForNode('crew_1', ['agent_id', 'tier'])).toHaveLength(0)
  })

  it('renders a code this build has never heard of', () => {
    // `BuilderProblem.code` admits `| string` precisely so a server that grew a
    // check is not silently ignored by an older canvas.
    const index = indexOf([problem('some-future-check', { node_id: 'agent_1' })])

    expect(index.unplacedForNode('agent_1').map((entry) => entry.message)).toEqual([
      "the server's sentence about some-future-check",
    ])
  })
})

describe('severity decides the rim, and an error is never softened by a sibling', () => {
  it('reports error for a node carrying one error and three warnings', () => {
    const index = indexOf([
      problem('router-branch-unconnected', { severity: 'warning', node_id: 'route_1' }),
      problem('cycle-iterations', { node_id: 'route_1' }),
      problem('join-single-predecessor', { severity: 'warning', node_id: 'route_1' }),
    ])

    expect(index.worstByNode.value.get('route_1')).toBe('error')
  })

  it('reports warning for a node carrying only warnings', () => {
    const index = indexOf([
      problem('router-branch-unconnected', { severity: 'warning', node_id: 'route_1' }),
    ])

    expect(index.worstByNode.value.get('route_1')).toBe('warning')
    expect(index.errorCount.value).toBe(0)
    expect(index.warningCount.value).toBe(1)
  })

  it('treats a severity it does not recognise as an error', () => {
    // Under-reporting a blocker is the expensive direction: publish would be
    // offered, the compiler would refuse, and nothing on screen would explain
    // it. `severity` is typed, but the transport is JSON and the type is a
    // promise rather than a guarantee.
    const index = indexOf([
      { ...problem('node-count'), severity: 'critical' as unknown as 'error' },
    ])

    expect(index.errorCount.value).toBe(1)
    expect(index.warningCount.value).toBe(0)
  })

  it('gives an edge its own worst severity, independent of its endpoints', () => {
    const index = indexOf([
      problem('back-edge-not-router', { node_id: 'agent_1', edge_id: 'e1' }),
      problem('router-branch-unconnected', { severity: 'warning', node_id: 'agent_1' }),
    ])

    expect(index.worstByEdge.value.get('e1')).toBe('error')
    expect(index.worstByNode.value.get('agent_1')).toBe('error')
  })
})

describe('ordering puts what blocks publish above what does not', () => {
  it('lists every error before every warning, preserving the server order inside each', () => {
    const index = indexOf([
      problem('no-output-node', { severity: 'warning' }),
      problem('node-count'),
      problem('join-single-predecessor', { severity: 'warning', node_id: 'score' }),
      problem('billable-count'),
    ])

    expect(index.ordered.value.map((entry) => entry.code)).toEqual([
      'node-count',
      'billable-count',
      'no-output-node',
      'join-single-predecessor',
    ])
  })

  it('reindexes when the list is replaced', () => {
    const source = shallowRef<BuilderProblem[]>([problem('node-count', { node_id: 'a' })])
    const index = useBuilderProblems(source)
    expect(index.problemsForNode('a')).toHaveLength(1)

    source.value = []

    expect(index.problemsForNode('a')).toEqual([])
    expect(index.errorCount.value).toBe(0)
  })
})

/* --- sink two: the offending control ----------------------------------- */

function mountField(problems: BuilderProblem[], field = 'max_turns') {
  const index = useBuilderProblems(shallowRef(problems))
  return mount(FieldProblem, {
    props: { nodeId: 'gate_1', field },
    global: { provide: { [BUILDER_PROBLEMS as symbol]: index } },
    slots: {
      default: (slotProps: { describedBy?: string; invalid?: string }) =>
        h('input', {
          'data-testid': 'control',
          'aria-describedby': slotProps.describedBy,
          'aria-invalid': slotProps.invalid,
        }),
    },
  })
}

describe('the server sentence is rendered under the control it is about', () => {
  it('prints the message verbatim, with no rewording', () => {
    const message =
      'this gate allows 5 turns; a cycle may run at most 3 times, so turns above that are ignored'
    const wrapper = mountField([
      { code: 'cycle-iterations', severity: 'error', message, node_id: 'gate_1', edge_id: null },
    ])

    expect(wrapper.text()).toContain(message)
  })

  it('wires aria-describedby from the control to the message', () => {
    const wrapper = mountField([
      {
        code: 'cycle-iterations',
        severity: 'error',
        message: 'too many turns',
        node_id: 'gate_1',
        edge_id: null,
      },
    ])

    const describedBy = wrapper.get('[data-testid="control"]').attributes('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(wrapper.get(`#${describedBy}`).text()).toContain('too many turns')
  })

  it('marks the control invalid for an error', () => {
    const wrapper = mountField([
      {
        code: 'cycle-iterations',
        severity: 'error',
        message: 'too many turns',
        node_id: 'gate_1',
        edge_id: null,
      },
    ])

    expect(wrapper.get('[data-testid="control"]').attributes('aria-invalid')).toBe('true')
  })

  it('does NOT mark the control invalid for a warning', () => {
    // The three warning codes describe a graph that is legal and probably not
    // what was meant. Announcing the control as invalid would tell a
    // screen-reader user the opposite of what the Publish button does.
    const wrapper = mountField(
      [
        {
          code: 'router-branch-unconnected',
          severity: 'warning',
          message: 'this branch goes nowhere',
          node_id: 'gate_1',
          edge_id: null,
        },
      ],
      'branches',
    )

    const control = wrapper.get('[data-testid="control"]')
    expect(control.attributes('aria-invalid')).toBeUndefined()
    expect(control.attributes('aria-describedby')).toBeTruthy()
    expect(wrapper.text()).toContain('this branch goes nowhere')
  })

  it('leaves a clean control with neither attribute set', () => {
    const wrapper = mountField([])
    const control = wrapper.get('[data-testid="control"]')

    expect(control.attributes('aria-describedby')).toBeUndefined()
    expect(control.attributes('aria-invalid')).toBeUndefined()
    expect(wrapper.find('.field-problem-list').exists()).toBe(false)
  })

  it('refuses to mount without the index rather than silently showing nothing', () => {
    // A blank space where a message belongs is the one outcome this package
    // exists to prevent, so an unprovided index fails loudly at mount.
    expect(() => mount(FieldProblem, { props: { nodeId: 'gate_1', field: 'max_turns' } })).toThrow(
      /BUILDER_PROBLEMS/,
    )
  })
})

/* --- sink three: the panel ---------------------------------------------- */

function mountPanel(props: {
  problems: BuilderProblem[]
  phase?: 'idle' | 'checking' | 'stale' | 'fresh' | 'unreachable'
  publishProblems?: BuilderProblem[]
  labels?: Record<string, string>
  /** The stored version on screen, or null while head is being edited (D-15-17). */
  viewingVersion?: number | null
}) {
  return mount(ProblemsPanel, {
    props: { phase: 'fresh' as const, publishProblems: [], labels: {}, ...props },
  })
}

const rowCodes = (wrapper: ReturnType<typeof mountPanel>): string[] =>
  wrapper.findAll('.problem-row').map((row) => row.get('.problem-code').text())

function codesOf(events: unknown[][] | undefined): string[] {
  return (events ?? []).map((event) => (event[0] as BuilderProblem).code)
}

describe('the panel shows every problem at once, worst first', () => {
  it('counts errors and warnings in the header', () => {
    const wrapper = mountPanel({
      problems: [
        problem('node-count'),
        problem('billable-count'),
        problem('no-output-node', { severity: 'warning' }),
      ],
    })

    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('2 errors · 1 warning')
  })

  it('lists whole-graph problems first, then anchored ones, errors before warnings', () => {
    const wrapper = mountPanel({
      problems: [
        problem('router-branch-unconnected', { severity: 'warning', node_id: 'route_1' }),
        problem('cycle-iterations', { node_id: 'gate_1' }),
        problem('no-output-node', { severity: 'warning' }),
        problem('node-count'),
      ],
    })

    expect(rowCodes(wrapper)).toEqual([
      'node-count',
      'no-output-node',
      'cycle-iterations',
      'router-branch-unconnected',
    ])
  })

  it('renders the anchor by label, falling back to the id rather than to blank', () => {
    const wrapper = mountPanel({
      problems: [
        problem('cycle-iterations', { node_id: 'gate_1' }),
        problem('node-unreachable', { node_id: 'agent_9' }),
      ],
      labels: { gate_1: 'Confirm scope' },
    })

    const anchors = wrapper.findAll('.problem-anchor').map((node) => node.text())
    expect(anchors).toEqual(['Confirm scope', 'agent_9'])
  })

  it('says a whole-graph problem is anchored to the whole graph', () => {
    const wrapper = mountPanel({ problems: [problem('billable-count')] })
    expect(wrapper.get('.problem-anchor').text()).toBe('whole graph')
  })

  it('is a live region, so a fixed problem is announced without a focus move', () => {
    const wrapper = mountPanel({ problems: [problem('node-count')] })
    const region = wrapper.get('#problems-list')

    expect(region.attributes('role')).toBe('log')
    expect(region.attributes('aria-live')).toBe('polite')
  })

  it('states the rule once, in the clean state', () => {
    const wrapper = mountPanel({ problems: [] })

    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('Ready to publish')
    expect(wrapper.text()).toContain('Warnings never block; errors always do.')
  })

  describe('a stored version is never "ready to publish" (D-15-17)', () => {
    it('says the document bar\'s own words instead, with a lock', () => {
      const wrapper = mountPanel({ problems: [], viewingVersion: 1 })

      const headline = wrapper.get('[data-testid="problems-headline"]')
      expect(headline.text()).toBe('viewing v1 · read-only')
      // Not the clean tick: `Ready to publish` is a claim about what the
      // author can DO next, and on a stored version that is nothing.
      expect(headline.classes()).not.toContain('is-clean')
      expect(wrapper.get('[data-testid="problems-read-only"]').text()).toContain(
        'publishing and editing act on head',
      )
      expect(wrapper.text()).not.toContain('Ready to publish')
    })

    it('does not read as blocking either, when the stored version has errors', () => {
      /*
       * The list is still shown - it is a true verdict about the document on
       * screen - but the RED headline would tell an author to go and fix
       * something they cannot edit.
       */
      const wrapper = mountPanel({
        problems: [problem('node-count'), problem('node-count')],
        viewingVersion: 3,
      })

      const headline = wrapper.get('[data-testid="problems-headline"]')
      expect(headline.text()).toBe('viewing v3 · read-only')
      expect(headline.classes()).not.toContain('is-blocking')
    })

    it('is unaffected while head is on screen', () => {
      const wrapper = mountPanel({ problems: [], viewingVersion: null })
      expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('Ready to publish')
      expect(wrapper.find('[data-testid="problems-read-only"]').exists()).toBe(false)
    })
  })
})

describe('the panel never presents a list as current when it is not', () => {
  it('dims and says checking while a validation is pending', () => {
    const wrapper = mountPanel({ problems: [problem('node-count')], phase: 'stale' })

    // Both at once, deliberately: the word tells you, the dimming stops you
    // reading the rows as fact. This is ChatDev's defining failure, and
    // shipping it in a nicer font is the one loss that would matter.
    expect(wrapper.get('[data-testid="problems-checking"]').text()).toBe('checking…')
    expect(wrapper.classes()).toContain('is-stale')
  })

  it('says nothing about checking once the answer is current', () => {
    const wrapper = mountPanel({ problems: [problem('node-count')], phase: 'fresh' })

    expect(wrapper.find('[data-testid="problems-checking"]').exists()).toBe(false)
    expect(wrapper.classes()).not.toContain('is-stale')
  })

  it('keeps the rows clickable while stale', () => {
    // A problem that was true 400ms ago is still the best guess available.
    // Disabling the rows would leave the author with nothing to act on.
    const wrapper = mountPanel({ problems: [problem('node-count')], phase: 'stale' })
    expect(wrapper.get('.problem-row').attributes('disabled')).toBeUndefined()
  })
})

describe('a publish refusal joins the same list rather than opening its own', () => {
  it('tags what publish added, and adds it once', () => {
    const shared = problem('billable-count')
    const wrapper = mountPanel({
      problems: [shared],
      publishProblems: [shared, problem('library-unbuildable-crew', { node_id: 'crew_1' })],
    })

    expect(rowCodes(wrapper)).toEqual(['billable-count', 'library-unbuildable-crew'])
    // The duplicate is dropped: two identical sentences read as two problems,
    // and the author would go looking for a second offending node.
    expect(wrapper.findAll('.problem-tag')).toHaveLength(1)
    expect(wrapper.get('.problem-tag').text()).toBe('from publish')
    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('2 errors')
  })
})

describe('a row is the way back to the thing it is about', () => {
  it('emits the problem when clicked, and leaves selection to the canvas', async () => {
    const target = problem('cycle-iterations', { node_id: 'gate_1' })
    const wrapper = mountPanel({ problems: [target] })

    await wrapper.get('.problem-row').trigger('click')

    // The panel owns no canvas and no inspector. `BuilderView` turns this into
    // select + fitView + focus the mapped field + the anchor flash; a panel
    // that reached into either would be a second opinion about what is
    // selected.
    expect(wrapper.emitted('focus')?.[0]).toEqual([target])
  })

  it('marks the clicked row as the current one', async () => {
    const wrapper = mountPanel({
      problems: [problem('node-count'), problem('billable-count')],
    })

    await wrapper.findAll('.problem-row')[1].trigger('click')

    const rows = wrapper.findAll('.problem-row')
    expect(rows[1].attributes('aria-current')).toBe('true')
    expect(rows[0].attributes('aria-current')).toBeUndefined()
  })

  it('walks forward and backward through the same path, wrapping at both ends', () => {
    const wrapper = mountPanel({
      problems: [
        problem('node-count'),
        problem('cycle-iterations', { node_id: 'gate_1' }),
        problem('no-output-node', { severity: 'warning' }),
      ],
    })
    const panel = wrapper.vm as unknown as { next: () => void; previous: () => void }

    // Document group first, then anchored - the same order the rows render in,
    // because F8 and a click are one code path.
    panel.next()
    panel.next()
    expect(codesOf(wrapper.emitted('focus'))).toEqual(['node-count', 'no-output-node'])

    panel.next()
    expect(codesOf(wrapper.emitted('focus'))[2]).toBe('cycle-iterations')

    // Wrapping rather than stopping: the list is short, the key is a survey
    // instrument, and a key that silently stops working reads as a broken key.
    panel.next()
    expect(codesOf(wrapper.emitted('focus'))[3]).toBe('node-count')

    // Backwards from the first row wraps to the LAST, not to the second - the
    // list is a ring in both directions or it is a ring in neither.
    panel.previous()
    expect(codesOf(wrapper.emitted('focus'))[4]).toBe('cycle-iterations')
  })

  it('walks nothing, and throws nothing, on a clean document', () => {
    const wrapper = mountPanel({ problems: [] })

    ;(wrapper.vm as unknown as { next: () => void }).next()

    expect(wrapper.emitted('focus')).toBeUndefined()
  })

  it('opens itself before walking, so the row it lands on can be seen', async () => {
    const wrapper = mountPanel({ problems: [problem('node-count')] })
    await wrapper.get('.problems-toggle').trigger('click')
    expect(wrapper.classes()).toContain('is-collapsed')

    ;(wrapper.vm as unknown as { next: () => void }).next()
    await wrapper.vm.$nextTick()

    expect(wrapper.classes()).not.toContain('is-collapsed')
  })
})
