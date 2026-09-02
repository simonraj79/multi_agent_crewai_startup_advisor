import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StateRefInput from '../src/components/builder/fields/StateRefInput.vue'
import ScalarInput from '../src/components/builder/fields/ScalarInput.vue'
import { nodeId } from '../src/types/builder'
import type { BuilderDocument, JsonScalar } from '../src/types/builder'
import {
  DOCUMENT_PY,
  agentNode,
  documentFixture,
  edge,
  inputNode,
  outputNode,
  problemsProvide,
} from './builderInspectorFixtures'

/**
 * A state reference is offered, not typed - and a reference the compiler cannot
 * resolve never leaves the client.
 *
 * The gap this closes is a 422 an author cannot act on.
 * `document.py::_checked_with_value` REFUSES any string carrying `${` that is
 * not the single flat key shape, because only that shape was ever measured
 * resolving: `${state.out__scoper.segment}` would otherwise reach the agent as
 * that exact text, eight characters of punctuation in the middle of a prompt
 * with nothing anywhere saying the reference did not resolve. That refusal is a
 * PARSE error, so the server answers it by naming a pydantic location rather
 * than a node - which is why §6.1 puts it in Tier 1 and why these tests assert
 * the widget refuses it and emits nothing at all.
 *
 * The out-of-scope case is the mirror image and is deliberately NOT refused: a
 * reference to a node that cannot reach this one is legal, compiles clean, and
 * simply resolves to nothing every run. That is the server's judgement to make,
 * so the widget says so and gets out of the way.
 */

function graph(): BuilderDocument {
  return documentFixture(
    [inputNode(), agentNode(), outputNode()],
    [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'result')],
  )
}

function mountRef(props: Record<string, unknown> = {}) {
  return mount(StateRefInput, {
    props: {
      modelValue: '',
      doc: graph(),
      label: 'Source',
      controlId: 'ref',
      field: 'source',
      where: 'source',
      ...props,
    },
    global: { provide: problemsProvide() },
  })
}

/**
 * The compiler's own sentence, reassembled from `document.py` rather than
 * retyped.
 *
 * A message rendered verbatim to an author is exactly the kind of restated
 * constant this repo has already watched drift five separate times, and the
 * failure here is quiet: the widget would keep refusing the right thing while
 * explaining it in words the server stopped using.
 */
function pythonNestedRefusal(where: string): string {
  const block = /def _checked_with_value[\s\S]*?raise ValueError\(([\s\S]*?)\n\s*\)/.exec(
    DOCUMENT_PY,
  )
  expect(block, 'the _checked_with_value refusal moved or changed shape').not.toBeNull()
  const pieces = [...(block as RegExpExecArray)[1].matchAll(/"([^"]*)"/g)].map((row) => row[1])
  return pieces
    .join('')
    .replace('{where}', where)
    // An f-string doubles a literal brace; the plain strings after it do not.
    .replaceAll('{{', '{')
    .replaceAll('}}', '}')
}

describe('the reference picker offers only keys that resolve', () => {
  it('lists the run input and one output key per node, each under its node label', async () => {
    const wrapper = mountRef()
    await wrapper.get('.ref-toggle').trigger('click')

    const keys = wrapper.findAll('.ref-option code').map((option) => option.text())
    expect(keys).toEqual(['idea', 'out__idea', 'out__scoper', 'out__result'])

    const labels = wrapper.findAll('.ref-option span').map((option) => option.text())
    expect(labels).toEqual(['the run input', 'Idea', 'Scoper', 'Result'])
  })

  it('emits the wrapped form when a key is picked', async () => {
    const wrapper = mountRef()
    await wrapper.get('.ref-toggle').trigger('click')
    await wrapper.findAll('.ref-option')[2].trigger('mousedown')

    expect(wrapper.emitted('commit')).toEqual([['${state.out__scoper}']])
  })

  it('emits the bare key in bare shape, because a router reads the state map directly', async () => {
    const wrapper = mountRef({ shape: 'bare', field: 'key' })
    await wrapper.get('.ref-toggle').trigger('click')
    await wrapper.findAll('.ref-option')[2].trigger('mousedown')

    expect(wrapper.emitted('commit')).toEqual([['out__scoper']])
  })

  it('narrows the list as the key is typed, and says so when nothing matches', async () => {
    const wrapper = mountRef()
    await wrapper.get('input').setValue('${state.out__sco')
    expect(wrapper.findAll('.ref-option code').map((option) => option.text())).toEqual([
      'out__scoper',
    ])

    await wrapper.get('input').setValue('${state.out__nothing')
    expect(wrapper.findAll('.ref-option')).toHaveLength(0)
    expect(wrapper.get('.ref-empty').text()).toContain('No key in this graph matches')
  })
})

describe('a nested reference is refused in the field, in the compiler’s own words', () => {
  it('renders the sentence document.py raises, verbatim', async () => {
    const wrapper = mountRef()
    await wrapper.get('input').setValue('${state.out__scoper.segment}')

    expect(wrapper.get('.field-hint').text()).toBe(pythonNestedRefusal('source'))
  })

  it('never emits it - the 422 is not sent', async () => {
    const wrapper = mountRef()
    const input = wrapper.get('input')
    await input.setValue('${state.out__scoper.segment}')
    await input.trigger('keydown.enter')
    await input.trigger('blur')

    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('puts the stored value back when the field is left holding one', async () => {
    const wrapper = mountRef({ modelValue: '${state.out__scoper}' })
    const input = wrapper.get('input')
    await input.setValue('${state.out__scoper.segment}')
    await input.trigger('blur')

    expect((input.element as HTMLInputElement).value).toBe('${state.out__scoper}')
    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('accepts a plain literal, and a well-formed reference', async () => {
    const wrapper = mountRef()
    const input = wrapper.get('input')
    await input.setValue('a plain sentence')
    await input.trigger('keydown.enter')
    await input.setValue('${state.idea}')
    await input.trigger('keydown.enter')

    expect(wrapper.emitted('commit')).toEqual([['a plain sentence'], ['${state.idea}']])
    expect(wrapper.find('.field-hint').exists()).toBe(false)
  })
})

describe('being out of scope warns and never refuses', () => {
  it('says a key is always empty when its node cannot reach this one', async () => {
    // `result` is downstream of `scoper`, so nothing upstream of `scoper`
    // produces `out__result`.
    const wrapper = mountRef({ nodeId: nodeId('scoper'), modelValue: '${state.out__result}' })

    expect(wrapper.get('.field-help').text()).toContain('cannot reach this node')
    expect(wrapper.find('.field-hint').exists()).toBe(false)
  })

  it('still emits it, because the schema allows it and the server owns the judgement', async () => {
    const wrapper = mountRef({ nodeId: nodeId('scoper') })
    const input = wrapper.get('input')
    await input.setValue('${state.out__result}')
    await input.trigger('keydown.enter')

    expect(wrapper.emitted('commit')).toEqual([['${state.out__result}']])
  })

  it('names a key no node produces at all', async () => {
    const wrapper = mountRef({ nodeId: nodeId('scoper'), modelValue: '${state.out__ghost}' })
    expect(wrapper.get('.field-help').text()).toContain('No node in this graph is called ghost')
  })

  it('has no opinion about a key the compiler seeds under another prefix', async () => {
    const wrapper = mountRef({ shape: 'bare', field: 'key', nodeId: nodeId('scoper'), modelValue: 'seeded_elsewhere' })
    expect(wrapper.find('.field-help').exists()).toBe(false)
    expect(wrapper.find('.field-hint').exists()).toBe(false)
  })
})

describe('a scalar declares its type instead of having one inferred', () => {
  function mountScalar(modelValue: JsonScalar) {
    return mount(ScalarInput, {
      props: { modelValue, doc: graph(), label: 'Value', controlId: 'val', field: 'value' },
      global: { provide: problemsProvide() },
    })
  }

  function pressType(wrapper: ReturnType<typeof mountScalar>, label: string) {
    const button = wrapper
      .findAll('.scalar-types button')
      .find((candidate) => candidate.text() === label)
    expect(button, `no ${label} button`).toBeTruthy()
    return button!.trigger('click')
  }

  it('round-trips a number, a boolean and a null as themselves', async () => {
    expect(mountScalar(7).get('input[type="number"]').attributes('value')).toBeUndefined()
    expect((mountScalar(7).get('input[type="number"]').element as HTMLInputElement).value).toBe('7')

    const boolean = mountScalar(true)
    expect(boolean.findAll('.segmented button')[0].attributes('aria-pressed')).toBe('true')

    expect(mountScalar(null).get('.scalar-null').text()).toContain('null')
  })

  it('keeps 0 and false, which a truthiness check would have eaten', async () => {
    const zero = mountScalar(0)
    expect((zero.get('input[type="number"]').element as HTMLInputElement).value).toBe('0')

    const untrue = mountScalar(false)
    expect(untrue.findAll('.segmented button')[1].attributes('aria-pressed')).toBe('true')
  })

  it('commits a real value of the new type the moment the type changes', async () => {
    const wrapper = mountScalar('0.7')
    await pressType(wrapper, 'num')
    expect(wrapper.emitted('commit')).toEqual([[0.7]])

    const second = mountScalar('anything')
    await pressType(second, 'null')
    expect(second.emitted('commit')).toEqual([[null]])
  })

  it('refuses a number box it cannot send, rather than emitting NaN', async () => {
    const wrapper = mountScalar(7)
    const input = wrapper.get('input[type="number"]')
    await input.setValue('')
    await input.trigger('blur')

    expect(wrapper.emitted('commit')).toBeUndefined()
    expect(wrapper.get('.field-hint').text()).toContain('Enter a number')
  })

  it('hands a string field to the reference picker, so `${` is refused there too', async () => {
    const wrapper = mountScalar('hello')
    expect(wrapper.findComponent(StateRefInput).exists()).toBe(true)

    await wrapper.get('input[type="text"]').setValue('${state.out__scoper.segment}')
    expect(wrapper.get('.field-hint').text()).toBe(pythonNestedRefusal('value'))
    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('offers no array and no object, because the schema accepts neither', () => {
    const offered = mountScalar('x')
      .findAll('.scalar-types button')
      .map((button) => button.text())
    expect(offered).toEqual(['str', 'num', 'bool', 'null'])
  })
})
