import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import blankFixture from './fixtures/templates/blank.json'
import conditionalRouterFixture from './fixtures/templates/conditional-router.json'
import fanOutJoinFixture from './fixtures/templates/fan-out-join.json'
import hierarchicalDelegationFixture from './fixtures/templates/hierarchical-delegation.json'
import ideaValidatorFixture from './fixtures/templates/idea-validator.json'
import minimalGatedAgentFixture from './fixtures/templates/minimal-gated-agent.json'
import newsToSocialFixture from './fixtures/templates/news-to-social.json'
import reflectionLoopFixture from './fixtures/templates/reflection-loop.json'
import sequentialPipelineFixture from './fixtures/templates/sequential-pipeline.json'
import rosterFixture from './fixtures/models.json'
import TemplateGallery from '../src/components/builder/TemplateGallery.vue'
import {
  ALL_BUILDER_TEMPLATES,
  BUILDER_TEMPLATES,
  MORE_BUILDER_TEMPLATES,
  documentFromTemplate,
} from '../src/data/builderTemplates'
import { resetModels } from '../src/data/models'
import { roster } from '../src/data/modelRoster'
import { MODEL_ROLES, resolvedRoles, roleOf } from '../src/data/templates/modelRoles'
import { NEWS_TO_SOCIAL_DOCUMENT } from '../src/data/templates/newsToSocial'
import { templateTestInputFor } from '../src/data/templates/testInputs'
import { forValidate } from '../src/utils/builderSerialize'
import type { BuilderDocument, ModelRoster } from '../src/types/builder'

/**
 * The gallery ships six graphs, and none of them is a picture of a graph.
 *
 * This is the client half of plan 14's proof; `tests/builder/test_templates.py`
 * is the server half and `tests/builder/test_client_fixtures.py` is what stops
 * the two describing different documents. What is asserted HERE is the one
 * thing only this side can answer: that the TypeScript modules still produce
 * the documents the recorded answers were computed from.
 *
 * WHY THAT MATTERS MORE THAN IT SOUNDS. A document written by hand into a `.ts`
 * file is never parsed by the compiler that will refuse it, so it can look
 * right for months and be a wall of 422s the first time somebody clicks the
 * card. The fixtures under `tests/fixtures/templates/` are generated from the
 * real `validate_document` and the real `estimate_budget`; a deep-equal against
 * the `document` half is what ties a green Python answer to the TypeScript this
 * build actually ships.
 *
 * EVERY BOUND IS READ FROM A FIXTURE'S VOCABULARY, never from a constant.
 * `MAX_BILLABLE_NODES` has already moved once - 8 to 13 - and a test asserting
 * `8` would have failed for being right.
 */

/**
 * One recorded answer, as this spec reads it.
 *
 * Declared rather than inferred from one of the imports. TypeScript widens a
 * JSON import to a literal type of that exact file, and eight templates have
 * eight different node shapes - so `typeof blankFixture` describes `blank` and
 * refuses the other seven. The cast is to a shape this file asserts against,
 * and the fixtures' real shape is proved on the Python side by
 * `tests/builder/test_client_fixtures.py`, which regenerates and byte-compares
 * them.
 */
interface TemplateFixture {
  readonly document: BuilderDocument
  readonly vocabulary: { readonly bounds: Record<string, number> }
  readonly validation: {
    readonly valid: boolean
    readonly problems: readonly unknown[]
    readonly budget: {
      readonly static_cost_usd: number
      readonly floor_cost_usd: number
      readonly modelled_calls: number
      readonly billable_nodes: number
      readonly escalation_nodes: number
      readonly cycles: number
      readonly unpriced_models: readonly string[]
      readonly over_ceiling: boolean
      readonly ceiling_usd: number
      readonly margin: number
    }
  }
}

const FIXTURES = {
  blank: blankFixture,
  'sequential-pipeline': sequentialPipelineFixture,
  'news-to-social': newsToSocialFixture,
  'conditional-router': conditionalRouterFixture,
  'reflection-loop': reflectionLoopFixture,
  'hierarchical-delegation': hierarchicalDelegationFixture,
  'idea-validator': ideaValidatorFixture,
  'minimal-gated-agent': minimalGatedAgentFixture,
  'fan-out-join': fanOutJoinFixture,
} as unknown as Record<string, TemplateFixture>

/** The regeneration recipe, in the order it has to be run. */
const REGENERATE =
  'node scripts/dump-templates.mjs && ./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py'

beforeEach(() => {
  resetModels()
  // The roster the fixtures were generated against, so a role token resolves
  // here to what it resolved to there. Assigned rather than fetched: this spec
  // is about the documents, not about the load.
  roster.value = rosterFixture as unknown as ModelRoster
})

describe('the gallery ships seven templates and keeps two more', () => {
  it('offers them in the order plan 14 D7 declares', () => {
    expect(BUILDER_TEMPLATES.map((template) => template.id)).toEqual([
      'blank',
      'sequential-pipeline',
      // Smaller than the pipeline above it and still after it: the ordering
      // rule is conceptual load, not node count, and this one carries an idea
      // neither neighbour does - a graph with no gate.
      'news-to-social',
      'conditional-router',
      'reflection-loop',
      'hierarchical-delegation',
      'idea-validator',
    ])
    expect(BUILDER_TEMPLATES).toHaveLength(7)
  })

  it('keeps the two library-agent templates in a second row', () => {
    // Owner's decision 21: `e2e/builder.spec.ts` drives `minimal-gated-agent`
    // through the whole authoring journey, so deleting it would turn a template
    // change into a suite change.
    expect(MORE_BUILDER_TEMPLATES.map((template) => template.id)).toEqual([
      'minimal-gated-agent',
      'fan-out-join',
    ])
    expect(ALL_BUILDER_TEMPLATES).toHaveLength(9)
  })

  it('has a fixture for every template and a template for every fixture', () => {
    expect(Object.keys(FIXTURES).sort()).toEqual(
      ALL_BUILDER_TEMPLATES.map((template) => template.id).sort(),
    )
  })
})

describe('each template is the document its recorded answer answered', () => {
  for (const template of ALL_BUILDER_TEMPLATES) {
    it(`${template.id} matches its fixture byte for byte`, () => {
      // Deep equality rather than a hash, so a failure names the field that
      // moved instead of two hex strings that differ.
      expect(
        forValidate(documentFromTemplate(template)),
        `${template.id} has drifted from its fixture. Regenerate with:\n    ${REGENERATE}`,
      ).toEqual(FIXTURES[template.id].document)
    })

    it(`${template.id} was answered valid with no problems`, () => {
      const validation = FIXTURES[template.id].validation
      expect(validation.valid).toBe(true)
      expect(validation.problems).toEqual([])
    })

    it(`${template.id} is priced, and fits under the ceiling with the margin`, () => {
      const budget = FIXTURES[template.id].validation.budget
      // An unpriced model contributes NOTHING to a total, so it reads as free
      // rather than as unknown - the confusion that once reported a
      // 128,069-token run at $0.00.
      expect(budget.unpriced_models).toEqual([])
      expect(budget.over_ceiling).toBe(false)
      // The margin multiplies the STATIC price, not the floor. Printing the two
      // adjacent without saying so invites the wrong sum.
      expect(budget.static_cost_usd * budget.margin).toBeLessThan(budget.ceiling_usd)
      expect(budget.floor_cost_usd).toBeLessThanOrEqual(budget.static_cost_usd)
    })
  }
})

describe('a template names a model by role, never by slug', () => {
  it('resolves the three roles from the roster rather than from a literal', () => {
    const answers = resolvedRoles(rosterFixture as unknown as ModelRoster)
    for (const role of MODEL_ROLES) {
      expect(answers[role], role).toBeTruthy()
      expect(rosterFixture.models.map((model) => model.id)).toContain(
        String(answers[role]).replace(/:.*$/, ''),
      )
    }
    // Three DISTINCT price points, or the templates teach nothing about cost.
    expect(new Set(Object.values(answers)).size).toBe(3)
  })

  it('leaves a token in place when the roster cannot answer, rather than guessing', () => {
    // `data/models.ts`'s rule, not a new one: a client-side stand-in for a model
    // id is how a canvas starts offering models the compiler has never heard of.
    roster.value = null
    const document = documentFromTemplate(
      BUILDER_TEMPLATES.find((template) => template.id === 'sequential-pipeline')!,
    )
    const models = document.nodes
      .map((node) => (node.config as { llm?: { model: string } }).llm?.model)
      .filter((model): model is string => Boolean(model))
    expect(models.length).toBeGreaterThan(0)
    expect(models.every((model) => roleOf(model) !== null)).toBe(true)
  })

  it('resolves every authored model when the roster is loaded', () => {
    for (const template of ALL_BUILDER_TEMPLATES) {
      const document = documentFromTemplate(template)
      for (const node of document.nodes) {
        const config = node.config as { llm?: { model: string } }
        if (!config.llm) continue
        expect(roleOf(config.llm.model), `${template.id}/${node.id}`).toBeNull()
      }
    }
  })

  it('hands out a fresh copy, so resolution cannot leak into the singleton', () => {
    const template = BUILDER_TEMPLATES.find((entry) => entry.id === 'reflection-loop')!
    const first = documentFromTemplate(template)
    const second = documentFromTemplate(template)
    expect(first).toEqual(second)
    expect(first).not.toBe(template.document)
    expect(first.nodes[0]).not.toBe(second.nodes[0])
    // The singleton still says `{{workhorse}}`; only the copies were resolved.
    const singleton = template.document.nodes.find((node) => node.id === 'generate')!
    expect(roleOf((singleton.config as { llm: { model: string } }).llm.model)).toBe('workhorse')
  })
})

describe('every template fits inside the bounds this build publishes', () => {
  for (const template of ALL_BUILDER_TEMPLATES) {
    it(`${template.id} is inside the served bounds`, () => {
      const bounds = FIXTURES[template.id].vocabulary.bounds
      const budget = FIXTURES[template.id].validation.budget
      const document = template.document
      expect(document.nodes.length).toBeLessThanOrEqual(bounds.max_graph_nodes)
      expect(budget.billable_nodes).toBeLessThanOrEqual(bounds.max_billable_nodes)
      expect(budget.escalation_nodes).toBeLessThanOrEqual(bounds.max_escalation_nodes)
      expect(budget.cycles).toBeLessThanOrEqual(bounds.max_cycles)
      expect(document.name.length).toBeLessThanOrEqual(bounds.max_name_chars)
      for (const node of document.nodes) {
        expect(node.label.length, `${template.id}/${node.id}`).toBeLessThanOrEqual(
          bounds.max_label_chars,
        )
        // R12: `Position` declares `int`, so `120.5` is a hard 422 on the first
        // save with nothing on screen to explain it.
        expect(Number.isInteger(node.position.x)).toBe(true)
        expect(Number.isInteger(node.position.y)).toBe(true)
      }
    })
  }
})

describe('the gallery card says what the picture cannot', () => {
  function galleryApi() {
    const calls: unknown[] = []
    return {
      calls,
      api: {
        validate: vi.fn(async (document: BuilderDocument) => {
          calls.push(document)
          const match = ALL_BUILDER_TEMPLATES.find(
            (template) => template.document.name === document.name,
          )
          return {
            valid: true,
            problems: [],
            budget: FIXTURES[match!.id].validation.budget,
          }
        }),
        list: vi.fn(async () => []),
        remove: vi.fn(async () => undefined),
      },
    }
  }

  it('renders teaches, modifyFirst and both counts on every card', async () => {
    const { api } = galleryApi()
    const wrapper = mount(TemplateGallery, { props: { api: api as never } })
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    const cards = wrapper.findAll('.template-card')
    expect(cards).toHaveLength(ALL_BUILDER_TEMPLATES.length)
    for (const [index, template] of ALL_BUILDER_TEMPLATES.entries()) {
      const text = cards[index].text()
      expect(text, template.id).toContain(template.title)
      expect(text, template.id).toContain(template.teaches)
      expect(text, template.id).toContain(template.modifyFirst)
      expect(text, template.id).toContain(String(template.document.nodes.length))
      expect(text, template.id).toContain(String(template.document.edges.length))
    }
  })

  it('prices every card from the server answer rather than from a literal', async () => {
    const { api } = galleryApi()
    const wrapper = mount(TemplateGallery, { props: { api: api as never } })
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()

    expect(api.validate).toHaveBeenCalledTimes(ALL_BUILDER_TEMPLATES.length)
    const card = wrapper
      .findAll('.template-card')
      .find((entry) => entry.text().includes('Reflection loop'))!
    const budget = FIXTURES['reflection-loop'].validation.budget
    // BOTH figures, never the enforced one alone: `static_cost_usd` carries the
    // nitro margin on every cheap node, so showing it by itself reads as an
    // error beside anyone's mental arithmetic.
    expect(card.text()).toContain(`$${budget.floor_cost_usd.toFixed(2)}`)
    expect(card.text()).toContain(`$${budget.static_cost_usd.toFixed(2)}`)
  })

  it('renders both caveats verbatim and gives nobody else one', async () => {
    const { api } = galleryApi()
    const wrapper = mount(TemplateGallery, { props: { api: api as never } })
    await wrapper.vm.$nextTick()

    // Two, and both earn it: the flagship's shape is not its judgement, and
    // `news-to-social` has no gate, so a link handed to somebody signed out
    // answers 403 rather than running. Asserted VERBATIM because R14's whole
    // point is that a caveat is not summarised on the way to the screen.
    const withCaveat = ALL_BUILDER_TEMPLATES.filter((template) => template.caveat)
    expect(withCaveat.map((template) => template.id)).toEqual([
      'news-to-social',
      'idea-validator',
    ])
    const caveats = wrapper.findAll('.template-caveat')
    expect(caveats).toHaveLength(withCaveat.length)
    for (const [index, template] of withCaveat.entries()) {
      expect(caveats[index].text()).toBe(template.caveat)
    }
  })

  it('puts the two library templates in a demoted second row', async () => {
    const { api } = galleryApi()
    const wrapper = mount(TemplateGallery, { props: { api: api as never } })
    await wrapper.vm.$nextTick()

    const more = wrapper.find('.template-more')
    expect(more.exists()).toBe(true)
    // OPEN, and the reason is arithmetic rather than taste: the grid resolves to
    // four columns, so six cards and eight cards occupy the same two rows.
    // Shutting it saves no space and hides the card six E2E specs click.
    expect((more.element as HTMLDetailsElement).open).toBe(true)
    expect(more.find('summary').text()).toContain(String(MORE_BUILDER_TEMPLATES.length))
    // The demotion is real: these two are not in the first grid.
    const rows = wrapper.findAll('.template-grid')
    expect(rows).toHaveLength(2)
    expect(rows[0].findAll('.template-card')).toHaveLength(BUILDER_TEMPLATES.length)
    expect(rows[1].findAll('.template-card')).toHaveLength(MORE_BUILDER_TEMPLATES.length)
  })
})

/* ── the news template, asserted as a graph rather than as a row ──────────── */

describe('news-to-social is the smallest graph that still does a whole job', () => {
  const document = NEWS_TO_SOCIAL_DOCUMENT
  const byId = new Map(document.nodes.map((node) => [String(node.id), node]))

  it('is a line of two billable nodes with one tool hung off the first', () => {
    expect(document.nodes.map((node) => `${node.id}:${node.kind}`)).toEqual([
      'subject:input',
      'research:agent',
      'search:tool',
      'write:agent',
      'post:output',
    ])
    expect(document.edges.map((edge) => `${edge.source}->${edge.target}@${edge.target_port}`)).toEqual([
      'subject->research@in',
      'research->write@in',
      'write->post@in',
      'search->research@attach',
    ])
    // Nothing waits for anything, and there is no cycle to bound.
    expect(document.joins).toEqual({})
    expect(FIXTURES['news-to-social'].validation.budget.cycles).toBe(0)
    expect(FIXTURES['news-to-social'].validation.budget.billable_nodes).toBe(2)
  })

  it('researches on the cheap tier and writes on the escalation one', () => {
    // The tier is a DECLARATION the document is bounded and counted on, and the
    // model is what it is actually priced from - so a template that let the two
    // disagree would be counted at one tier and billed at another.
    const research = byId.get('research')!.config as { tier: string; max_iter: number; llm: { model: string } }
    const write = byId.get('write')!.config as { tier: string; llm: { model: string } }
    expect(research.tier).toBe('cheap')
    expect(roleOf(research.llm.model)).toBe('workhorse')
    expect(write.tier).toBe('escalation')
    expect(roleOf(write.llm.model)).toBe('escalation')
    // Low on purpose: the tool loop is where one node's price multiplies.
    expect(research.max_iter).toBe(3)
    expect(FIXTURES['news-to-social'].validation.budget.escalation_nodes).toBe(1)
  })

  it('attaches a KEYLESS search, which is what makes it cold-sign-in runnable', () => {
    // Not `firecrawl_search`, and the reason is measured rather than stylistic:
    // that entry is `credential_optional=False` unconditionally, so a template
    // naming it opens with `tool-credential-required` on a graph nobody has
    // touched. The recorded answer below is what proves this one does not.
    const tool = byId.get('search')!.config as { tool_id: string; params: Record<string, unknown> }
    expect(tool.tool_id).toBe('analyze_community_sentiment')
    expect(tool.params).toEqual({})
    expect(FIXTURES['news-to-social'].validation.valid).toBe(true)
    expect(FIXTURES['news-to-social'].validation.problems).toEqual([])
  })

  it('has no gate, and says so where somebody about to share a link reads it', () => {
    expect(document.nodes.some((node) => node.kind === 'gate')).toBe(false)
    const card = BUILDER_TEMPLATES.find((template) => template.id === 'news-to-social')!
    expect(card.caveat).toContain('403')
    expect(card.caveat).toContain('signed-in')
  })

  it('names its own input field, because a sample resolves by field', () => {
    // `sequential-pipeline` already declares `topic`, and `SAMPLE_BY_FIELD` is
    // keyed by field - so sharing one would silently hand one template the
    // other's prompt. The prompt VARIABLE is still `{topic}`; only the state
    // key differs, which is the distinction the node exists to show.
    expect(String(document.input_field)).toBe('subject')
    const research = byId.get('research')!.config as { prompt_inputs: Record<string, string> }
    expect(research.prompt_inputs).toEqual({ topic: '${state.subject}' })
    expect(templateTestInputFor('subject')?.value).toBe('AI agents and agentic workflows')
    expect(templateTestInputFor('topic')?.value).not.toBe(
      templateTestInputFor('subject')?.value,
    )
  })
})
