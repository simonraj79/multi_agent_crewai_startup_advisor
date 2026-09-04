import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProblemsPanel from '../src/components/builder/ProblemsPanel.vue'
import { runPhaseProblems } from '../src/composables/useBuilderProblems'
import type { NodeErrorFrameLike } from '../src/composables/useBuilderProblems'
import type { BuilderProblem } from '../src/types/builder'

/**
 * 12 D2's third surface: the problems dock says which node failed, too.
 *
 * The plan asks that a failed node say so in three places at once - on the
 * card, in the log, and here - and this is the one that makes a failure
 * SURVEYABLE. Four red nodes on a sixteen-node canvas is four rows in a list or
 * four hunts across a graph, and the dock already owns "every reason this is
 * not working, all at once, errors first, each one one click from the thing it
 * is about".
 *
 * TWO THINGS THIS FILE IS CAREFUL ABOUT, and both are ways the group could look
 * right and be wrong:
 *
 * 1. `stage: 'error'` is NOT the discriminator. `serializer.py:455` raises one
 *    for CrewAI's own `MethodExecutionFailedEvent`, and a tool, an llm call and
 *    a crew each raise another - four frames narrating one failure from the
 *    package's side. `attempt` is written only by `runtime.py::_node_error_frame`,
 *    so it is what tells a C6 frame from CrewAI's echo of it. Without that
 *    filter one failed node would be five rows.
 * 2. The run group must not change the PUBLISH verdict. "Ready to publish" is a
 *    claim about what an author can do next, and a run that already failed does
 *    not make a valid graph invalid - so the headline counts build-time
 *    problems only, and the group renders beside whatever that verdict is.
 */

function errorFrame(overrides: Partial<NodeErrorFrameLike['details']> & { node_id?: string } = {}) {
  const { node_id = 'b', ...details } = overrides as Record<string, unknown>
  return {
    node_id,
    details: {
      stage: 'error',
      error_class: 'auth',
      message: 'SyntheticBadCredential: credential rejected by openrouter',
      attempt: 1,
      will_retry: false,
      routed: false,
      ...details,
    },
  } as NodeErrorFrameLike
}

describe('runPhaseProblems', () => {
  it('turns a node_error frame into an anchored problem', () => {
    const [problem] = runPhaseProblems([errorFrame()])
    expect(problem.code).toBe('run-auth')
    expect(problem.severity).toBe('error')
    expect(problem.node_id).toBe('b')
    expect(problem.edge_id).toBeNull()
    expect(problem.message).toContain('credential rejected')
  })

  it('prefixes the class rather than inventing one', () => {
    // C8: run-phase classes surface through `node_error.error_class` and are
    // NOT union members. The suffix is the wire value verbatim; the prefix is
    // this module's, so `auth` does not sit in the code chip looking like a
    // build-time code this build has never heard of.
    for (const [errorClass, code] of [
      ['auth', 'run-auth'],
      ['tool_timeout', 'run-tool_timeout'],
      ['refusal', 'run-refusal'],
      ['schema', 'run-schema'],
      ['rate_limit', 'run-rate_limit'],
      ['credential-not-yours', 'run-credential-not-yours'],
    ] as const) {
      expect(runPhaseProblems([errorFrame({ error_class: errorClass })])[0].code).toBe(code)
    }
  })

  it('ignores the four frames CrewAI raises about the same failure', () => {
    // Each carries `stage: 'error'` and no `attempt`. A filter on stage alone
    // would render one failed node as five rows.
    const crewaiEchoes: NodeErrorFrameLike[] = [
      { node_id: 'b', details: { stage: 'error', message: 'n1_b failed' } },
      { node_id: 'b', details: { stage: 'error', message: 'search failed' } },
      { node_id: 'b', details: { stage: 'error', message: 'model call failed' } },
      { node_id: 'b', details: { stage: 'error', message: 'Crew failed' } },
    ]
    expect(runPhaseProblems(crewaiEchoes)).toEqual([])
    expect(runPhaseProblems([...crewaiEchoes, errorFrame()])).toHaveLength(1)
  })

  it('ignores every frame that is not an error at all', () => {
    expect(
      runPhaseProblems([
        { node_id: 'b', details: { stage: 'after', attempt: 1 } },
        { node_id: 'b', details: null },
        { node_id: null, details: { stage: 'error', attempt: 1 } },
        {},
      ]),
    ).toEqual([])
  })

  it('keeps the LAST attempt per node and says which it was', () => {
    const retried = [
      errorFrame({ error_class: 'rate_limit', attempt: 1, will_retry: true, message: 'a' }),
      errorFrame({ error_class: 'rate_limit', attempt: 2, will_retry: true, message: 'b' }),
      errorFrame({ error_class: 'rate_limit', attempt: 3, will_retry: false, message: 'c' }),
    ]
    const problems = runPhaseProblems(retried)
    expect(problems).toHaveLength(1)
    // The last one is the one whose `will_retry` is false and whose sentence
    // describes the state the run ended in. Nothing about the earlier attempts
    // is lost, because the count is carried into the sentence.
    expect(problems[0].message).toBe('c (attempt 3)')
  })

  it('reports one row per node when several fail', () => {
    const problems = runPhaseProblems([
      errorFrame({ node_id: 'a', error_class: 'refusal' }),
      errorFrame({ node_id: 'b', error_class: 'schema' }),
    ])
    expect(problems.map((entry) => entry.node_id)).toEqual(['a', 'b'])
  })

  it('degrades rather than blanking when the frame says little', () => {
    const [problem] = runPhaseProblems([
      { node_id: 'b', details: { stage: 'error', attempt: 1 } },
    ])
    expect(problem.code).toBe('run-error')
    expect(problem.message).toBe('the node failed')
  })
})

describe('the dock renders them under their own heading', () => {
  const runProblems: BuilderProblem[] = runPhaseProblems([errorFrame()])

  it('groups them separately, with the heading and the aria label', () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems, labels: { b: 'Draft' } },
    })
    expect(wrapper.find('[data-testid="problems-run-heading"]').text()).toContain('last run')
    expect(wrapper.find('ul[aria-label="Run problems"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="problem-run-auth"]').text()).toContain(
      'credential rejected',
    )
  })

  it('names the node by its LABEL, so a row is readable without the id', () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems, labels: { b: 'Draft' } },
    })
    expect(wrapper.find('[data-testid="problem-run-auth"]').text()).toContain('Draft')
  })

  it('does not claim the graph is ready to publish while one is on screen', () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems },
    })
    expect(wrapper.find('[data-testid="problems-headline"]').text()).toBe('1 node failed')
  })

  it('leaves the publish verdict alone when there are build problems too', () => {
    // The headline counts BUILD-time problems, because it answers "can this
    // publish" - and a run that already failed does not make a valid graph
    // invalid, nor a broken one worse.
    const wrapper = mount(ProblemsPanel, {
      props: {
        problems: [
          {
            code: 'no-input-node',
            severity: 'error',
            message: 'this graph has no input node.',
            node_id: null,
            edge_id: null,
          },
        ],
        phase: 'clean',
        runProblems,
      },
    })
    expect(wrapper.find('[data-testid="problems-headline"]').text()).toBe('1 error')
    expect(wrapper.find('ul[aria-label="Run problems"]').exists()).toBe(true)
    expect(wrapper.find('ul[aria-label="Whole-graph problems"]').exists()).toBe(true)
  })

  it('renders nothing extra when the last run was clean', () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems: [] },
    })
    expect(wrapper.find('[data-testid="problems-run-heading"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="problems-headline"]').text()).toBe('Ready to publish')
  })

  it('a row emits focus, so one click reaches the node that failed', async () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems },
    })
    await wrapper.find('[data-testid="problem-run-auth"]').trigger('click')
    const emitted = wrapper.emitted('focus')
    expect(emitted).toBeTruthy()
    expect((emitted![0][0] as BuilderProblem).node_id).toBe('b')
  })

  it('is walkable by F8 along with the rest', () => {
    const wrapper = mount(ProblemsPanel, {
      props: { problems: [], phase: 'clean', runProblems },
    })
    ;(wrapper.vm as unknown as { next: () => void }).next()
    expect(wrapper.emitted('focus')).toBeTruthy()
  })
})
