import type { TemplateTestInput } from '../../types/builder'

/**
 * A saved test input for every template that can be run - 13 criterion 11.
 *
 * WHY THESE ARE COMMITTED CONSTANTS AND NOT DATABASE ROWS. A row in
 * `builder_test_inputs` belongs to whoever wrote it, and the criterion is that
 * a template runs "from a cold stubbed sign-in with no configuration" - a
 * property of the BUILD, true for every author in their first minute, which a
 * per-user row cannot be. Seeding rows at sign-up is the alternative and it is
 * worse: it writes into somebody's own table something they did not ask for,
 * and it goes stale the moment a template's input field changes.
 *
 * WHY THEY RESOLVE BY `input_field` AND NOT BY TEMPLATE ID. A document carries
 * no provenance - `documentFromTemplate` clones the graph, and the template's
 * id is not among the fields it copies - so by the time the panel is open there
 * is nothing on the document that says which card it came from. The input field
 * IS on the document, and it is the exact thing a sample is a sample OF.
 *
 * THREE TEMPLATES SHARE `idea`, and that is why `templateId` below is a list.
 * The two library-agent templates and the flagship all take a startup idea, and
 * one sample serves all three because the field means the same thing in each -
 * pretending otherwise would put three near-identical strings in this file and
 * make the map look more precise than it is. What the test asserts is the
 * property that actually matters: every runnable template's field has a sample,
 * and no field has two.
 *
 * WHAT MAKES A GOOD SAMPLE HERE. Concrete enough that the graph's own shape is
 * visible in the answer - the router's value has to be classifiable, the
 * reflection loop's has to be something a critic can score - and short enough
 * to read in the box without scrolling. Prompts a first-time author would
 * recognise as ordinary, not demonstrations of the product.
 */
export const TEMPLATE_TEST_INPUTS: readonly TemplateTestInput[] = [
  {
    templateId: 'sequential-pipeline',
    label: 'Sample topic',
    value: 'How small clinics choose scheduling software in 2026',
  },
  {
    // The subject this template was written for. The researcher's own prompt
    // supplies the "last 7 days", so the box carries the SUBJECT and nothing
    // else - and a subject rather than a question, because the tool behind it
    // is a search and a search does better with nouns.
    //
    // Longer than the bare "AI agents" it stands for, and both halves of that
    // are deliberate: the phrase is a better query on a keyword search, and
    // `testPanel.spec.ts` requires every committed sample to be more than ten
    // characters - a sample too short to be a real prompt teaches nothing about
    // what to type.
    templateId: 'news-to-social',
    label: 'Sample subject',
    value: 'AI agents and agentic workflows',
  },
  {
    templateId: 'conditional-router',
    label: 'Sample request',
    value: 'My invoice charged me twice this month and I would like a refund.',
  },
  {
    templateId: 'reflection-loop',
    label: 'Sample ask',
    value: 'Write a 150-word explanation of vector embeddings for a product manager.',
  },
  {
    templateId: 'hierarchical-delegation',
    label: 'Sample brief',
    value: 'Plan the launch of a keyboard-first task manager for engineering teams.',
  },
  {
    templateId: 'idea-validator',
    label: 'Sample idea',
    value: 'An AI tool that turns Figma files into production React',
  },
]

/**
 * The `input_field` each sample answers for, and the templates that declare it.
 *
 * Restated rather than read off the template documents, and the reason is a
 * cycle: `builderTemplates.ts` has to be able to import this module to render a
 * card's sample, so importing that one back would make the two mutually
 * dependent - which in a Vite build resolves to one of them observing the other
 * half-initialised. `testPanel.spec.ts` reads the real documents and asserts
 * the two agree, which is the same bargain `serverLimits.ts` makes with
 * `config.py`.
 */
export const TEMPLATE_INPUT_FIELDS: Readonly<Record<string, readonly string[]>> = {
  'sequential-pipeline': ['topic'],
  // `subject` rather than `topic`, and the reason is this map: it is keyed by
  // FIELD, so a second template declaring `topic` would silently take over the
  // sequential pipeline's sample - `Object.fromEntries` keeps the last write.
  // The collision is structural rather than a naming preference; the note in
  // `newsToSocial.ts` carries it from the template's end.
  'news-to-social': ['subject'],
  'conditional-router': ['request'],
  'reflection-loop': ['ask'],
  'hierarchical-delegation': ['brief'],
  // `minimal-gated-agent` and `fan-out-join` declare `idea` too, and share this
  // one sample; `COVERED_TEMPLATE_IDS` is what names them.
  'idea-validator': ['idea'],
}

/**
 * Every template id this file speaks for, including the two that share a field
 * with the flagship. Read by the test that asserts the gallery is covered.
 */
export const COVERED_TEMPLATE_IDS: readonly string[] = [
  'sequential-pipeline',
  'news-to-social',
  'conditional-router',
  'reflection-loop',
  'hierarchical-delegation',
  'idea-validator',
  'minimal-gated-agent',
  'fan-out-join',
]

const SAMPLE_BY_FIELD: Readonly<Record<string, TemplateTestInput>> = Object.fromEntries(
  TEMPLATE_TEST_INPUTS.flatMap((sample) =>
    (TEMPLATE_INPUT_FIELDS[sample.templateId] ?? []).map((field) => [field, sample] as const),
  ),
)

/**
 * The committed sample for a document's own `input_field`, or null.
 *
 * Null for a graph an author drew themselves, which is the common case and not
 * a failure: the box is then empty and they type into it, which is what a text
 * input is for.
 */
export function templateTestInputFor(inputField: string): TemplateTestInput | null {
  return SAMPLE_BY_FIELD[inputField.trim()] ?? null
}
