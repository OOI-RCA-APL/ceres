import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'

import { ParticleModel } from '@/api/particles'
import CWorkspaceWidgetMeter from '@/components/c-workspace-widget-meter.vue'
import { MeterWidgetModel } from '@/workspace/models'

// A component whose `reading` records, with a `value` in kPa, come in on the declared connections,
// `one` labeled.
const declared = vi.hoisted(() => ({ connections: [] as string[] }))
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      get: () => ({
        particles: [
          {
            type: 'reading',
            fields: [{ name: 'value', schema: { type: 'number', unit: 'kPa' } }],
            connections: declared.connections,
          },
        ],
      }),
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

/** The sources meters read, and the newest record and the connections each reads. */
const sources = vi.hoisted(() => [] as unknown[])
const latest = vi.hoisted(() => ({
  particle: null as unknown,
  connections: [] as (string | null)[],
}))
vi.mock('@/particle-data', async () => {
  const { computed, toValue } = await import('vue')
  return {
    useLatestParticle: (source: () => unknown) => {
      sources.push(computed(() => toValue(source)))
      return {
        particle: computed(() => latest.particle),
        connections: computed(() => latest.connections),
      }
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

function render(connection: string | null, settings: object = {}) {
  const widget = reactive(
    MeterWidgetModel.parse({
      id: 'meter',
      type: 'meter',
      particleAddress: '@gauge',
      particleType: 'reading',
      particleField: 'value',
      particleConnection: connection,
      ...settings,
    }),
  )
  const meter = mount(CWorkspaceWidgetMeter, {
    props: { widget },
    global: {
      stubs: {
        'c-button': Button,
        'c-text': { template: '<p><slot /></p>' },
        'c-tooltip': { template: '<slot />' },
      },
    },
  })
  return { meter, widget }
}

/** A reading of `value` taken `minutesAgo` minutes ago. */
function reading(value: unknown, minutesAgo = 0) {
  return ParticleModel.parse({
    id: 'reading',
    address: '@gauge',
    timestamp: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    type: 'reading',
    connection: 'two',
    data: { value },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  latest.particle = null
  latest.connections = []
  declared.connections = ['one', 'two']
})

describe('a meter on a type with several connections', () => {
  it('asks which connection to show rather than blending them', () => {
    const { meter } = render(null)

    expect(meter.text()).toContain('Choose Connection')
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
    expect(meter.text()).not.toContain('Choose Connection')
    expect(sources.at(-1)).toMatchObject({ value: { connection: 'two' } })
  })

  it('shows a meter narrowed to one connection as it is', () => {
    expect(render('two').meter.text()).not.toContain('Choose Connection')
  })

  it('counts records naming no connection as a source of their own', () => {
    declared.connections = ['one']
    latest.connections = ['one', null]
    const { meter } = render(null)

    expect(meter.text()).toContain('Choose Connection')
    expect(meter.findAll('button').map((button) => button.text())).toEqual(['Port One'])
  })

  it('reads one declared connection as it is', () => {
    declared.connections = ['one']
    latest.connections = ['one']

    expect(render(null).meter.text()).not.toContain('Choose Connection')
  })
})

describe('a meter reading', () => {
  /** The value element of a meter on connection `two` reading `value`. */
  function valueOf(value: unknown, settings: object = {}, minutesAgo = 0) {
    latest.particle = reading(value, minutesAgo)
    return render('two', settings).meter.find('[data-meter-value]')
  }

  it('reads with the unit its field declares, or the one set', () => {
    expect(valueOf(3.14159).text()).toBe('3.14 kPa')
    expect(valueOf(3.14159, { unit: 'bar', decimals: 1 }).text()).toBe('3.1 bar')
  })

  it('takes the color of the bound it crosses, error over warning', () => {
    const settings = { warningAbove: 2, errorAbove: 5 }
    expect(valueOf(1, settings).classes()).not.toContain('text-warning')
    expect(valueOf(3, settings).classes()).toContain('text-warning')
    expect(valueOf(6, settings).classes()).toContain('text-error')
  })

  it('dims once its newest record is older than "Stale After"', () => {
    expect(valueOf(1, { staleAfter: '5m' }, 1).classes()).not.toContain('opacity-40')
    expect(valueOf(1, { staleAfter: '5m' }, 10).classes()).toContain('opacity-40')
  })
})
