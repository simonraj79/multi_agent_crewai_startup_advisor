import { shallowRef } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVueFlow } from '@vue-flow/core'
import BuilderCanvas from '../src/components/builder/BuilderCanvas.vue'
import TestPanel from '../src/components/builder/TestPanel.vue'
import { useBuilderCanvas } from '../src/composables/useBuilderCanvas'
import type { CanvasDocumentStore } from '../src/composables/useBuilderCanvas'
import {
  PANEL_COLLAPSED_PX,
  PANEL_MAX_FRACTION,
  PANEL_MIN_PX,
  TEST_TABS,
  ancestorsOf,
  useFlowTest,
} from '../src/composables/useFlowTest'
import type { FlowTest } from '../src/composables/useFlowTest'
import { ALL_BUILDER_TEMPLATES, documentFromTemplate } from '../src/data/builderTemplates'
import {
  COVERED_TEMPLATE_IDS,
  TEMPLATE_INPUT_FIELDS,
  TEMPLATE_TEST_INPUTS,
  templateTestInputFor,
} from '../src/data/templates/testInputs'
import type { BuilderTestApiLike } from '../src/services/builderApi'
import { FakeStudioApi, flush, frameFactory, withSetup } from './helpers'
import type {
  BuilderDocument,
  CompiledPreview,
  DryRunResult,
  RunStateResult,
  TestInput,
  TestInputDraft,
} from '../src/types/builder'
import compiledPreviewFixture from './fixtures/builderCompiledPreview.json'

/**
 * The docked test panel - .agent/plans/13-flow-testing.md, criteria 1-6 and 11.
 *
 * What this file is FOR, and what it deliberately cannot answer. Every
 * assertion below is about structure and about what goes on the wire: which
 * mode a Run posts, which node states a frame produces, that a mock nobody
 * supplied is named before a request is made, that the Code tab renders the
 * strings the PYTHON renderer produced rather than strings a TypeScript author
 * invented. None of it is about how tall the panel ended up or whether the
 * canvas actually re-fitted on screen - "a jsdom mount asserts structure and
 * never asks how wide anything ended up" is this repository's own most
 * expensive lesson, and `e2e/test-panel.spec.ts` is where those questions have
 * an answer.
 *
 * The one exception is the re-fit PATH, which is asserted here by driving a
 * stub `ResizeObserver` - not because a browser is unnecessary, but because the
 * wiring (does the canvas observe the panel at all) is a different question
 * from the outcome (did the graph end up fitted), and only the second needs a
 * layout engine.
 */

/* ── doubles ──────────────────────────────────────────────────────────── */

const PREVIEW = compiledPreviewFixture as unknown as CompiledPreview & {
  credential: { id: string; label: string }
}

const DRY_RUN: DryRunResult = {
  valid: false,
  problems: [
    {
      code: 'library-missing-prompt-input',
      severity: 'error',
      message: 'the scoper needs an idea',
      node_id: 'draft',
      edge_id: null,
    },
    {
      code: 'crew-tier-not-honoured',
      severity: 'warning',
      message: 'tier does not choose a model for a library crew',
      node_id: 'team',
      edge_id: null,
    },
  ],
  budget: {
    static_cost_usd: 1.5137,
    floor_cost_usd: 1.2159,
    modelled_calls: 60,
    billable_nodes: 8,
    escalation_nodes: 5,
    cycles: 2,
    unpriced_models: [],
  },
  definition: {
    methods: {
      n0_idea: { start: true },
      n1_draft: { listen: 'n0_idea' },
    },
  },
}

/**
 * The builder half of the panel's transport.
 *
 * Declared `implements BuilderTestApiLike`, so the compiler forces it to match
 * its subject: a double that quietly diverges from the thing it stands in for
 * certifies nothing, which is the lesson closed items 15 and 33 both record and
 * which `FakeStudioApi` already obeys next door.
 */
class FakeBuilderApi implements BuilderTestApiLike {
  rows: TestInput[] = []
  created: Array<{ documentId: string; draft: TestInputDraft }> = []
  deleted: string[] = []
  dryRuns: Array<{ sessionId: string; workflowId: string }> = []
  states: Array<{ runId: string; step?: number }> = []
  stateAnswer: RunStateResult = { run_id: 'run-under-test', step: 0, state: {} }
  compiledCalls: string[] = []

  async listTestInputs(): Promise<TestInput[]> {
    return [...this.rows]
  }

  async createTestInput(documentId: string, draft: TestInputDraft): Promise<TestInput> {
    this.created.push({ documentId, draft })
    const row: TestInput = {
      id: `ti_${this.created.length.toString().padStart(12, '0')}`,
      document_id: documentId,
      label: draft.label,
      inputs: draft.inputs,
      node_mocks: draft.node_mocks ?? {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    this.rows = [row, ...this.rows]
    return row
  }

  async deleteTestInput(_documentId: string, testInputId: string): Promise<void> {
    this.deleted.push(testInputId)
    this.rows = this.rows.filter((row) => row.id !== testInputId)
  }

  async compiled(documentId: string): Promise<CompiledPreview> {
    this.compiledCalls.push(documentId)
    return PREVIEW
  }

  async dryRun(sessionId: string, workflowId: string): Promise<DryRunResult> {
    this.dryRuns.push({ sessionId, workflowId })
    return DRY_RUN
  }

  async runState(runId: string, step?: number): Promise<RunStateResult> {
    this.states.push({ runId, step })
    return { ...this.stateAnswer, step: step ?? 0 }
  }
}

/**
 * The document surface `useBuilderCanvas` needs, and nothing else.
 *
 * `useBuilderDocument` is the real store and does not satisfy
 * `CanvasDocumentStore` - its `addNode` takes an options bag where the canvas
 * passes two positional arguments - so a canvas test that reached for it would
 * be a canvas test that does not compile. Every method here is a no-op: what
 * these two tests are about is the layout observer and one attribute, and a
 * store that recorded commits would be a store whose recordings nothing reads.
 */
class InertStore implements CanvasDocumentStore {
  readonly doc = shallowRef(graph())
  addNode(): void {}
  addEdge(): void {}
  moveNodes(): void {}
  deleteSelection(): void {}
  setEdgePort(): void {}
  retargetEdge(): void {}
  setJoin(): void {}
}

/** A two-agent line with a tool on the first, which is the smallest useful graph. */
function graph(): BuilderDocument {
  return documentFromTemplate(
    ALL_BUILDER_TEMPLATES.find((template) => template.id === 'sequential-pipeline')!,
  )
}

interface Harness {
  test: FlowTest
  api: FakeBuilderApi
  studio: FakeStudioApi
  fetchMock: ReturnType<typeof vi.fn>
  app: { unmount(): void }
}

function makeTest(overrides: { published?: boolean; documentId?: string | null } = {}): Harness {
  const api = new FakeBuilderApi()
  const studio = new FakeStudioApi()
  const document = graph()
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 202,
    headers: new Headers(),
    json: async () => ({ run_id: 'run-under-test', status: 'queued', graph_version: 'v1' }),
    text: async () => '{}',
  })
  globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch
  const [test, app] = withSetup(() =>
    useFlowTest({
      document: () => document,
      documentId: () => (overrides.documentId === undefined ? 'ug_0a1b2c3d' : overrides.documentId),
      published: () => overrides.published !== false,
      api,
      transport: studio,
    }),
  )
  return { test, api, studio, fetchMock, app }
}

/** The body of the nth POST the panel put on the wire. */
function sentBody(fetchMock: ReturnType<typeof vi.fn>, call = 0): Record<string, unknown> {
  const init = fetchMock.mock.calls[call][1] as RequestInit
  return JSON.parse(String(init.body)) as Record<string, unknown>
}

let originalFetch: typeof globalThis.fetch

beforeEach(() => {
  originalFetch = globalThis.fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.unstubAllGlobals()
})

/* ── criterion 1: the panel itself ────────────────────────────────────── */

describe('the panel is docked, collapsed, resizable and never modal', () => {
  function mountPanel(harness: Harness) {
    return mount(TestPanel, {
      props: { test: harness.test, labels: { scoper: 'Researcher' } },
      attachTo: window.document.body,
    })
  }

  it('mounts collapsed to a tab strip, with all five tabs reachable', () => {
    const harness = makeTest()
    const wrapper = mountPanel(harness)

    expect(harness.test.open.value).toBe(false)
    expect(harness.test.panelHeight.value).toBe(PANEL_COLLAPSED_PX)
    expect(wrapper.attributes('data-open')).toBe('false')
    for (const tab of TEST_TABS) {
      expect(wrapper.find(`[data-testid="test-tab-${tab}"]`).exists()).toBe(true)
    }
    expect(TEST_TABS).toHaveLength(5)

    wrapper.unmount()
    harness.app.unmount()
  })

  it('opens on the tab that was pressed rather than on whichever was last', async () => {
    const harness = makeTest()
    const wrapper = mountPanel(harness)

    await wrapper.find('[data-testid="test-tab-dry"]').trigger('click')

    expect(harness.test.open.value).toBe(true)
    expect(harness.test.tab.value).toBe('dry')
    expect(wrapper.find('[data-testid="test-tab-dry"]').attributes('aria-selected')).toBe('true')

    wrapper.unmount()
    harness.app.unmount()
  })

  it('clamps the dragged height between 160px and 60% of the pane', () => {
    const harness = makeTest()
    harness.test.paneHeight.value = 900
    harness.test.toggle(true)

    harness.test.setHeight(40)
    expect(harness.test.panelHeight.value).toBe(PANEL_MIN_PX)

    harness.test.setHeight(5000)
    expect(harness.test.panelHeight.value).toBe(Math.round(900 * PANEL_MAX_FRACTION))
    expect(harness.test.maxHeight.value).toBe(540)

    harness.test.setHeight(300)
    expect(harness.test.panelHeight.value).toBe(300)

    harness.app.unmount()
  })

  it('clamps on READ, so a height stored on a tall window comes back on a short one', () => {
    const harness = makeTest()
    harness.test.paneHeight.value = 1200
    harness.test.toggle(true)
    harness.test.setHeight(700)
    expect(harness.test.panelHeight.value).toBe(700)

    harness.test.paneHeight.value = 500
    expect(harness.test.panelHeight.value).toBe(300)

    harness.app.unmount()
  })

  it('renders no dialog on any of the five tabs (R15)', async () => {
    const harness = makeTest()
    harness.test.toggle(true)
    const wrapper = mountPanel(harness)

    for (const tab of TEST_TABS) {
      harness.test.selectTab(tab)
      await flush(2)
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(wrapper.find('dialog').exists()).toBe(false)
      expect(wrapper.find('.modal').exists()).toBe(false)
    }

    wrapper.unmount()
    harness.app.unmount()
  })

  it('gives the drag handle a separator role a keyboard can move', async () => {
    const harness = makeTest()
    harness.test.paneHeight.value = 900
    harness.test.toggle(true)
    const wrapper = mountPanel(harness)
    const handle = wrapper.find('[data-testid="test-panel-handle"]')

    expect(handle.attributes('role')).toBe('separator')
    expect(handle.attributes('aria-valuemin')).toBe(String(PANEL_MIN_PX))

    const before = harness.test.panelHeight.value
    await handle.trigger('keydown', { key: 'ArrowUp' })
    expect(harness.test.panelHeight.value).toBe(before + 16)

    wrapper.unmount()
    harness.app.unmount()
  })
})

describe('opening the panel re-fits the canvas (the ResizeObserver path)', () => {
  /*
   * The same mechanism the version browser already uses, on the other side of
   * the graph: the canvas observes an element the shell hands it, and re-fits
   * when that element GROWS after the author's first gesture. Driving a stub
   * observer proves the wiring; whether the graph ends up fitted is a layout
   * question and `e2e/builder-layout.spec.ts` is where it is asked.
   */
  interface Driven {
    callback: ResizeObserverCallback
    targets: Element[]
  }

  it('observes a panel that arrives after mount and re-fits when it grows', async () => {
    const instances: Driven[] = []
    class DrivenResizeObserver {
      private readonly entry: Driven
      constructor(callback: ResizeObserverCallback) {
        this.entry = { callback, targets: [] }
        instances.push(this.entry)
      }
      observe(target: Element): void {
        this.entry.targets.push(target)
      }
      unobserve(target: Element): void {
        this.entry.targets = this.entry.targets.filter((one) => one !== target)
      }
      disconnect(): void {}
    }
    vi.stubGlobal('ResizeObserver', DrivenResizeObserver)

    const canvas = useBuilderCanvas({ document: new InertStore() })
    const wrapper = mount(BuilderCanvas, {
      props: { canvas, label: 'under test' },
      slots: { node: '<div class="stub-node" />', edge: '<g class="stub-edge" />' },
      attachTo: window.document.body,
    })
    const flow = useVueFlow('builder-flow')
    const fitView = vi.spyOn(flow, 'fitView').mockImplementation(async () => true)
    const observer = instances.find((entry) => entry.targets.includes(wrapper.element))!
    expect(observer).toBeDefined()

    const panel = window.document.createElement('div')
    await wrapper.setProps({ panel })
    await flush(2)
    expect(observer.targets).toContain(panel)

    // The author has gestured, so only a GROW re-fits - the rule the dock
    // already follows, and the reason the problems panel growing mid-edit does
    // not move the canvas under the next drag.
    await wrapper.trigger('pointerdown')
    await wrapper.trigger('pointerup')
    observer.callback(
      [{ target: panel, contentRect: { height: 260 } } as unknown as ResizeObserverEntry],
      {} as ResizeObserver,
    )
    expect(fitView).toHaveBeenCalledTimes(1)

    observer.callback(
      [{ target: panel, contentRect: { height: 36 } } as unknown as ResizeObserverEntry],
      {} as ResizeObserver,
    )
    expect(fitView).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('carries the run mode onto the canvas as one attribute', async () => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    )
    const canvas = useBuilderCanvas({ document: new InertStore() })
    const wrapper = mount(BuilderCanvas, {
      props: { canvas, label: 'under test' },
      slots: { node: '<div class="stub-node" />', edge: '<g class="stub-edge" />' },
      attachTo: window.document.body,
    })

    expect(wrapper.attributes('data-mode')).toBe('design')
    await wrapper.setProps({ mode: 'run' })
    expect(wrapper.attributes('data-mode')).toBe('run')

    wrapper.unmount()
  })
})

/* ── criterion 2: the Run tab ─────────────────────────────────────────── */

describe('the Run tab posts mode: test and paints the canvas', () => {
  it('posts the mode, the chosen saved input and the graph its own field', async () => {
    const harness = makeTest()
    harness.api.rows = [
      {
        id: 'ti_abcdef012345',
        document_id: 'ug_0a1b2c3d',
        label: 'A topic',
        inputs: { topic: 'clinic scheduling' },
        node_mocks: {},
        created_at: 'x',
        updated_at: 'x',
      },
    ]
    await harness.test.loadTestInputs()
    await flush(2)

    expect(harness.test.selectedInputId.value).toBe('ti_abcdef012345')
    expect(harness.test.inputValue.value).toBe('clinic scheduling')

    await harness.test.startRun()
    await flush(4)

    const body = sentBody(harness.fetchMock)
    expect(body.mode).toBe('test')
    expect(body.test_input_id).toBe('ti_abcdef012345')
    expect(body.workflow_id).toBe('ug_0a1b2c3d')
    expect(body.inputs).toEqual({ topic: 'clinic scheduling' })
    // `human`, because `create_run` answers 403 for an ANONYMOUS `auto` unless
    // `VALIDATOR_ALLOW_AUTO_GATES` is set - which the free E2E backend does not.
    expect(body.gates).toBe('human')

    harness.app.unmount()
  })

  it('turns NODE_START and NODE_END frames into the canvas states the CSS draws', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)

    const build = frameFactory('run-under-test')
    harness.studio.emit(
      build('node_state', { event_type: 'START', node_id: 'scoper', message: 'Researcher' }),
    )
    await flush(4)
    expect(harness.test.run.nodeStates.scoper).toBe('running')

    harness.studio.emit(build('node_state', { event_type: 'END', node_id: 'scoper' }))
    await flush(4)
    expect(harness.test.run.nodeStates.scoper).toBe('completed')

    harness.studio.emit(
      build('node_state', { event_type: 'END', node_id: 'writer', level: 'ERROR' }),
    )
    await flush(4)
    expect(harness.test.run.nodeStates.writer).toBe('error')

    harness.app.unmount()
  })

  it('collects an utterance into the log under the node that said it', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)

    const build = frameFactory('run-under-test')
    harness.studio.emit(
      build('agent', {
        event_type: 'AGENT_COMPLETED',
        node_id: 'scoper',
        message: 'Three sources found.',
      }),
    )
    await flush(4)

    const entries = harness.test.run.chatEntries.value
    expect(entries.length).toBeGreaterThan(0)
    expect(entries.some((entry) => entry.nodeId === 'scoper')).toBe(true)

    harness.app.unmount()
  })

  it('refuses to run an unpublished graph, and says which button fixes it', () => {
    const harness = makeTest({ published: false })

    expect(harness.test.canRun.value).toBe(false)
    expect(harness.test.runBlockedReason.value).toContain('Publish')

    harness.app.unmount()
  })

  it('refuses a graph that has never been saved', () => {
    const harness = makeTest({ documentId: null })

    expect(harness.test.canRun.value).toBe(false)
    expect(harness.test.runBlockedReason.value).toContain('Save')

    harness.app.unmount()
  })
})

/* ── criterion 3: the Node tab ────────────────────────────────────────── */

describe('the Node tab tests one node against mocked ancestors', () => {
  it('offers flow-kind nodes only, because an attachment has no output', () => {
    const harness = makeTest()
    const offered = harness.test.testableNodes.value.map((node) => node.kind)

    expect(offered.length).toBeGreaterThan(0)
    expect(offered).not.toContain('tool')
    expect(offered).not.toContain('mcp')
    expect(offered).not.toContain('skill')

    harness.app.unmount()
  })

  it('names every missing out__ key rather than posting a run that will 422', async () => {
    const harness = makeTest()
    harness.api.rows = [
      {
        id: 'ti_nomocks00000',
        document_id: 'ug_0a1b2c3d',
        label: 'no mocks',
        inputs: { topic: 'clinic scheduling' },
        node_mocks: {},
        created_at: 'x',
        updated_at: 'x',
      },
    ]
    await harness.test.loadTestInputs()
    const last = harness.test.testableNodes.value.at(-1)!
    harness.test.nodeUnderTest.value = last.id

    expect(harness.test.missingMocks.value.length).toBeGreaterThan(0)
    expect(harness.test.canRunNode.value).toBe(false)
    expect(harness.fetchMock).not.toHaveBeenCalled()

    harness.app.unmount()
  })

  it('posts mode: node_test with the node and the input once the mocks are there', async () => {
    const harness = makeTest()
    const document = graph()
    const last = harness.test.testableNodes.value.at(-1)!
    const mocks = Object.fromEntries(
      ancestorsOf(document, last.id).map((id) => [id, 'a mocked answer']),
    )
    harness.api.rows = [
      {
        id: 'ti_withmocks00',
        document_id: 'ug_0a1b2c3d',
        label: 'with mocks',
        inputs: { topic: 'clinic scheduling' },
        node_mocks: mocks,
        created_at: 'x',
        updated_at: 'x',
      },
    ]
    await harness.test.loadTestInputs()
    harness.test.nodeUnderTest.value = last.id

    expect(harness.test.missingMocks.value).toEqual([])
    expect(harness.test.canRunNode.value).toBe(true)

    await harness.test.startNodeTest()
    await flush(4)

    const body = sentBody(harness.fetchMock)
    expect(body.mode).toBe('node_test')
    expect(body.node_id).toBe(last.id)
    expect(body.test_input_id).toBe('ti_withmocks00')

    harness.app.unmount()
  })

  it('walks ancestors transitively and skips attachment edges', () => {
    const document = graph()
    const attachments = new Set(
      document.nodes
        .filter((node) => ['tool', 'mcp', 'skill'].includes(node.kind))
        .map((node) => String(node.id)),
    )
    const last = document.nodes.filter((node) => !attachments.has(String(node.id))).at(-1)!
    const walked = ancestorsOf(document, String(last.id))

    expect(walked.length).toBeGreaterThan(1)
    for (const id of walked) expect(attachments.has(id)).toBe(false)
  })
})

/* ── criterion 4: the Dry-run tab ─────────────────────────────────────── */

describe('the Dry-run tab spends nothing and says so', () => {
  it('asks the dry-run route and creates no run', async () => {
    const harness = makeTest()

    await harness.test.runDryRun()

    expect(harness.api.dryRuns).toEqual([
      { sessionId: 'builder-dry-run', workflowId: 'ug_0a1b2c3d' },
    ])
    // `''`, the console's own "no run", and not null: a dry run creates none.
    expect(harness.test.run.runId.value).toBe('')
    expect(harness.fetchMock).not.toHaveBeenCalled()

    harness.app.unmount()
  })

  it('renders both budget figures, the call count, the problems and the free sentence', async () => {
    const harness = makeTest()
    harness.test.toggle(true)
    harness.test.selectTab('dry')
    const wrapper = mount(TestPanel, {
      props: { test: harness.test, labels: {} },
      attachTo: window.document.body,
    })

    await harness.test.runDryRun()
    await flush(4)

    expect(wrapper.find('[data-testid="test-dry-free"]').text()).toContain('no tokens were spent')
    expect(wrapper.find('[data-testid="test-dry-floor"]').text()).toBe('$1.2159')
    expect(wrapper.find('[data-testid="test-dry-static"]').text()).toBe('$1.5137')
    expect(wrapper.find('[data-testid="test-dry-calls"]').text()).toBe('60')
    const problems = wrapper.find('[data-testid="test-dry-problems"]').text()
    expect(problems).toContain('library-missing-prompt-input')
    expect(problems).toContain('crew-tier-not-honoured')
    expect(wrapper.find('[data-testid="test-dry-plan"]').text()).toContain('n0_idea')

    wrapper.unmount()
    harness.app.unmount()
  })
})

/* ── criterion 5: the Code tab ────────────────────────────────────────── */

describe('the Code tab renders what the Python renderer produced', () => {
  it('shows the YAML and the Python from the generated fixture', async () => {
    const harness = makeTest()
    harness.test.toggle(true)
    harness.test.selectTab('code')
    const wrapper = mount(TestPanel, {
      props: { test: harness.test, labels: {} },
      attachTo: window.document.body,
    })
    await flush(6)

    expect(harness.api.compiledCalls).toEqual(['ug_0a1b2c3d'])
    expect(wrapper.find('[data-testid="code-yaml"]').text()).toBe(PREVIEW.yaml.trimEnd())
    expect(wrapper.find('[data-testid="code-python"]').text()).toBe(PREVIEW.python.trimEnd())

    wrapper.unmount()
    harness.app.unmount()
  })

  it('shows a credential as its label, and never as its id', async () => {
    const harness = makeTest()
    harness.test.toggle(true)
    harness.test.selectTab('code')
    const wrapper = mount(TestPanel, {
      props: { test: harness.test, labels: {} },
      attachTo: window.document.body,
    })
    await flush(6)

    const python = wrapper.find('[data-testid="code-python"]').text()
    expect(python).toContain(`<credential: ${PREVIEW.credential.label}>`)
    expect(python).not.toContain(PREVIEW.credential.id)

    wrapper.unmount()
    harness.app.unmount()
  })

  it('is the one tab an unpublished draft can still use', async () => {
    const harness = makeTest({ published: false })
    await harness.test.loadCompiled()

    expect(harness.api.compiledCalls).toEqual(['ug_0a1b2c3d'])
    expect(harness.test.compiled.value).not.toBeNull()

    harness.app.unmount()
  })
})

/* ── criterion 6: the State tab ───────────────────────────────────────── */

describe('the State tab reads one frame and groups the reserved keys', () => {
  it('asks for the state at the frame seq the slider names', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)

    await harness.test.loadState(7)

    expect(harness.api.states).toEqual([{ runId: 'run-under-test', step: 7 }])
    expect(harness.test.stateStep.value).toBe(7)

    harness.app.unmount()
  })

  it('groups out__, err__, turns__ and __builder__ apart from the author keys', async () => {
    const harness = makeTest()
    harness.api.stateAnswer = {
      run_id: 'run-under-test',
      step: 3,
      state: {
        topic: 'clinic scheduling',
        out__scoper: 'a scoped idea',
        err__writer: 'ValueError: nope',
        turns__confirm: 2,
        __builder__: { version: 1 },
      },
    }
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)
    await harness.test.loadState(3)

    const groups = harness.test.stateGroups.value
    expect(groups.map((group) => group.prefix)).toEqual([
      '',
      'out__',
      'err__',
      'turns__',
      '__builder__',
    ])
    expect(groups[0].entries.map((entry) => entry.key)).toEqual(['topic'])
    // The prefix is stripped for READING, so the label is the node's own id.
    expect(groups[1].entries[0].label).toBe('scoper')
    expect(groups[1].entries[0].key).toBe('out__scoper')

    harness.app.unmount()
  })

  it('drops a group with nothing in it rather than drawing an empty heading', async () => {
    const harness = makeTest()
    harness.api.stateAnswer = {
      run_id: 'run-under-test',
      step: 1,
      state: { out__scoper: 'a scoped idea' },
    }
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)
    await harness.test.loadState(1)

    expect(harness.test.stateGroups.value.map((group) => group.prefix)).toEqual(['out__'])

    harness.app.unmount()
  })

  it('renders nothing to inspect until a run has happened', () => {
    const harness = makeTest()
    harness.test.toggle(true)
    harness.test.selectTab('state')
    const wrapper = mount(TestPanel, {
      props: { test: harness.test, labels: {} },
      attachTo: window.document.body,
    })

    expect(wrapper.find('[data-testid="test-state-empty"]').exists()).toBe(true)

    wrapper.unmount()
    harness.app.unmount()
  })
})

/* ── criterion 11: a sample for every runnable template ───────────────── */

describe('every template a cold sign-in can open has an input it can run', () => {
  it('covers every gallery template that takes an input', () => {
    const gallery = ALL_BUILDER_TEMPLATES.map((template) => template.id).filter(
      (id) => id !== 'blank',
    )
    for (const id of gallery) {
      expect(COVERED_TEMPLATE_IDS, `${id} has no committed test input`).toContain(id)
    }
  })

  it('names the field each template actually declares', () => {
    /*
     * The map is restated rather than read off the documents (a cycle -
     * `builderTemplates.ts` must be able to import the samples), so the drift
     * is a failing test rather than a silently wrong default. The same bargain
     * `serverLimits.ts` makes with `config.py`.
     */
    for (const [templateId, fields] of Object.entries(TEMPLATE_INPUT_FIELDS)) {
      const template = ALL_BUILDER_TEMPLATES.find((row) => row.id === templateId)
      expect(template, `${templateId} is not a gallery template`).toBeDefined()
      const document = documentFromTemplate(template!)
      expect(fields).toContain(String(document.input_field))
    }
  })

  it('resolves a sample for every covered template by its own input field', () => {
    for (const id of COVERED_TEMPLATE_IDS) {
      const template = ALL_BUILDER_TEMPLATES.find((row) => row.id === id)!
      const document = documentFromTemplate(template)
      const sample = templateTestInputFor(String(document.input_field))
      expect(sample, `${id} resolves no sample`).not.toBeNull()
      expect(sample!.value.trim().length).toBeGreaterThan(10)
    }
  })

  it('gives a graph nobody templated an empty box rather than somebody else prompt', () => {
    expect(templateTestInputFor('a_field_no_template_declares')).toBeNull()
    expect(templateTestInputFor('')).toBeNull()
  })

  it('seeds the Run tab from the sample, so a template runs with no configuration', async () => {
    const harness = makeTest()
    expect(harness.test.inputValue.value).toBe('')

    await harness.test.loadTestInputs()

    const sample = TEMPLATE_TEST_INPUTS.find((row) => row.templateId === 'sequential-pipeline')!
    expect(harness.test.inputValue.value).toBe(sample.value)
    expect(harness.test.canRun.value).toBe(true)

    harness.app.unmount()
  })

  it('never overwrites something the author has typed', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'mine'

    await harness.test.loadTestInputs()

    expect(harness.test.inputValue.value).toBe('mine')

    harness.app.unmount()
  })
})

/* ── saved inputs, both writes ────────────────────────────────────────── */

describe('saving an input, with and without the last run outputs', () => {
  it('sends the label and the one field the document declares', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'

    await harness.test.saveTestInput('A topic')

    expect(harness.api.created).toEqual([
      {
        documentId: 'ug_0a1b2c3d',
        draft: { label: 'A topic', inputs: { topic: 'clinic scheduling' }, from_run_id: undefined },
      },
    ])
    expect(harness.test.selectedInputId.value).toBe(harness.api.rows[0].id)

    harness.app.unmount()
  })

  it('sends from_run_id rather than mocks assembled in the browser', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.startRun()
    await flush(4)

    await harness.test.saveTestInput('From the run', { fromLastRun: true })

    expect(harness.api.created[0].draft.from_run_id).toBe('run-under-test')
    expect(harness.api.created[0].draft.node_mocks).toBeUndefined()

    harness.app.unmount()
  })

  it('deletes a row and forgets the selection that pointed at it', async () => {
    const harness = makeTest()
    harness.test.inputValue.value = 'clinic scheduling'
    await harness.test.saveTestInput('A topic')
    const id = harness.api.rows[0].id

    await harness.test.removeTestInput(id)

    expect(harness.api.deleted).toEqual([id])
    expect(harness.test.selectedInputId.value).toBeNull()

    harness.app.unmount()
  })
})

/* ── the transport, which is the whole of the reuse ───────────────────── */

describe('the run transport refuses a demonstration', () => {
  it('will not start a test run against a mocked backend', async () => {
    const harness = makeTest()
    harness.studio.mode = 'mock'
    harness.test.inputValue.value = 'clinic scheduling'

    await harness.test.startRun()
    await flush(4)

    expect(harness.fetchMock).not.toHaveBeenCalled()
    expect(harness.test.problem.value).toContain('demonstration')

    harness.app.unmount()
  })
})
