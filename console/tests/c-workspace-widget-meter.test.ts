import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'

import CWorkspaceWidgetMeter from '@/components/c-workspace-widget-meter.vue'
import { MeterWidgetModel } from '@/workspace/models'

// A component whose `reading` records come in on two connections, `one` labeled.
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      get: () => ({ particles: [{ type: 'reading', fields: [], connections: ['one', 'two'] }] }),
      getConnection: (_address: string, name: string) =>
        name === 'one' ? { name, label: 'Port One' } : null,
    },
  }),
}))

const editable = vi.hoisted(() => ({ value: true }))
vi.mock('@/workspace', () => ({
  useWorkspace: () => ({
    resolveAddress: (raw: unknown) => raw,
    get canEdit() {
      return editable.value
    },
  }),
}))

const sources = vi.hoisted(() => [] as unknown[])
vi.mock('@/particle-data', async () => {
  const { computed, toValue } = await import('vue')
  return {
    useLatestParticle: (source: () => unknown) => {
      sources.push(computed(() => toValue(source)))
      return { particle: computed(() => null) }
    },
  }
})

// Renders the choice buttons as plain buttons carrying their labels.
const Button = defineComponent({
  props: { label: { type: String, default: '' } },
  emits: ['click'],
  setup(props, { emit }) {
    return () => h('button', { onClick: () => emit('click') }, props.label)
  },
})

function render(connection: string | null) {
  const widget = reactive(
    MeterWidgetModel.parse({
      id: 'meter',
      type: 'meter',
      particleAddress: '@gauge',
      particleType: 'reading',
      particleField: 'value',
      particleConnection: connection,
    }),
  )
  const meter = mount(CWorkspaceWidgetMeter, {
    props: { widget },
    global: { stubs: { 'c-button': Button, 'c-text': { template: '<p><slot /></p>' } } },
  })
  return { meter, widget }
}

describe('a meter on a type with several connections', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('asks which connection to show rather than blending them', () => {
    const { meter } = render(null)

    expect(meter.text()).toContain('Choose a connection')
    expect(meter.findAll('button').map((button) => button.text())).toEqual(['Port One', 'two'])
  })

  it('stores the choice for an editor', async () => {
    editable.value = true
    const { meter, widget } = render(null)

    await meter.find('button').trigger('click')
    await flushPromises()

    expect(widget.particleConnection).toBe('one')
  })

  it('shows a viewer the choice without storing it', async () => {
    editable.value = false
    const { meter, widget } = render(null)

    await meter.findAll('button')[1]!.trigger('click')
    await flushPromises()

    expect(widget.particleConnection ?? null).toBeNull()
    expect(meter.text()).not.toContain('Choose a connection')
    expect(sources.at(-1)).toMatchObject({ value: { connection: 'two' } })
  })

  it('shows a meter narrowed to one connection as it is', () => {
    expect(render('two').meter.text()).not.toContain('Choose a connection')
  })
})
