import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { ParticleModel } from '@/api/particles'
import CWorkspaceWidgetChart from '@/components/c-workspace-widget-chart.vue'
import { fixedRange, useTimeRangeViews } from '@/time-range'
import { ChartWidgetModel } from '@/workspace/models'

/** The chart's fetches in the order it makes them, each answered when its test resolves it. */
const fetches = vi.hoisted(() => [] as ((particles: unknown[]) => void)[])
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: { get: () => null, getConnection: () => null },
    particles: { getAll: () => new Promise((resolve) => fetches.push(resolve)) },
  }),
}))

/** Hands a record to the chart's stream for its first group. */
const streamed = vi.hoisted(() => ({ receive: (_record: unknown, _stream: unknown) => {} }))
vi.mock('@/api/client', () => ({
  useClient: () => ({
    useStream: (options: { onReceive: (record: unknown, stream: unknown) => void }) => {
      streamed.receive = options.onReceive
    },
  }),
}))

vi.mock('@/workspace', () => ({ useWorkspace: () => ({ resolveAddress: (raw: unknown) => raw }) }))
vi.mock('@/preferences', () => ({ usePreferences: () => ({ isDarkModeEnabled: false }) }))

/** What each line last held, as the chart handed it to ECharts. */
const lines = vi.hoisted(() => new Map<string, unknown[]>())
const Chart = defineComponent({
  setup(_props, { expose }) {
    expose({
      setOption(option: { series?: { id: string; data?: unknown[] }[] }) {
        for (const series of option.series ?? []) {
          if (series.data != null) {
            lines.set(series.id, series.data)
          }
        }
      },
      getOption: () => ({}),
    })
    return () => h('div')
  },
})

const minute = 60_000

/** A `reading` record with `value`, taken `minutesAgo` minutes ago. */
function reading(id: string, value: number, minutesAgo: number) {
  return ParticleModel.parse({
    id,
    address: '@gauge',
    timestamp: new Date(Date.now() - minutesAgo * minute).toISOString(),
    type: 'reading',
    data: { value },
  })
}

function receive(record: unknown) {
  streamed.receive(record, { id: '0', path: '/api/particles' })
}

/** Mounts a live chart of the last hour of `reading` values and lets it start its first load. */
async function render() {
  mount(CWorkspaceWidgetChart, {
    props: {
      widget: ChartWidgetModel.parse({
        id: 'chart',
        type: 'chart',
        timespan: 60 * 60,
        particles: [
          { address: '@gauge', type: 'reading', series: [{ id: 'value', field: 'value' }] },
        ],
      }),
    },
    global: {
      stubs: {
        'c-chart': Chart,
        'c-time-range': { template: '<div><slot /></div>' },
        'c-tooltip': { template: '<slot />' },
        'c-button': true,
      },
    },
  })
  await vi.advanceTimersByTimeAsync(100)
}

/** The values the `value` line draws, once the pending batch applies. */
async function drawn() {
  await vi.advanceTimersByTimeAsync(2000)
  return (lines.get('value') ?? []).map((entry) => (entry as [number, number])[1])
}

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  fetches.length = 0
  lines.clear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('a chart widget', () => {
  it('draws nothing from a load whose range changed before it answered', async () => {
    await render()
    useTimeRangeViews().get('chart')!.range = fixedRange(
      Date.now() - 30 * minute,
      Date.now() - 20 * minute,
    )!
    await flushPromises()

    fetches[0]!([reading('a', 1, 10)])

    expect(await drawn()).not.toContain(1)
  })

  it('draws a record once when the load in flight also returns it', async () => {
    await render()
    receive(reading('a', 1, 1))

    fetches[0]!([reading('a', 1, 1)])

    expect(await drawn()).toEqual([1])
  })

  it('drops a live record from before the window', async () => {
    await render()
    fetches[0]!([reading('a', 1, 10)])
    await flushPromises()

    receive(reading('b', 99, 120))

    expect(await drawn()).toEqual([1])
  })

  it('keeps a record arriving late in time order', async () => {
    await render()
    fetches[0]!([reading('a', 1, 10)])
    await flushPromises()

    receive(reading('b', 2, 5))
    receive(reading('c', 3, 20))

    expect(await drawn()).toEqual([3, 1, 2])
  })
})
