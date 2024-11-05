<script lang="ts" setup>
import { ECharts } from 'echarts'
import moment from 'moment'
import { computed, watch } from 'vue'

import { useClient, Stream } from '@/api/client'
import { useEngine } from '@/api/engine'
import { ParticleModel, Particle } from '@/api/particles'
import { Option, DataValue } from '@/chart'
import Chart from '@/components/Chart.vue'
import { useTime } from '@/time'
import { debouncedComputed, parseDuration } from '@/utilities'
import { ChartWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()
const client = useClient()
const time = useTime()
let instance = $ref<ECharts | null>(null)

type Results = Record<string, DataValue[][]>

let data: Results = $ref({})
let streamedData: Results = $ref({})
let loading = $ref(true)
let appended = $ref(0)

const start = $computed(() => {
  const timespan = parseDuration(widget.timespan)
  if (widget.after == null && widget.before == null) {
    return moment.utc(time.now).subtract(timespan)
  }
  if (widget.after != null) {
    return moment.utc(widget.after).add(timespan)
  }

  return moment.utc(widget.before).subtract(timespan)
})

const end = $computed(() => {
  if (widget.before != null) {
    return moment.utc(widget.before)
  }

  return null
})

const duration = $computed(() => moment.duration(moment.utc(end ?? time.now).diff(start)))

// Actual x-axis bounds for the chart.
const bounds = $computed(() => {
  const current = moment.utc(start)
  // Shrink the actual x-axis range slightly to avoid flickering between interval scales when new
  // data is appended and the `duration` is a boundary value such as one hour.
  const shrink = duration.asMilliseconds() / 100
  return {
    start: current.subtract(shrink / 2, 'ms').valueOf(),
    end: current.add(shrink / 2, 'ms').valueOf(),
  }
})

async function getData() {
  const mapping = {} as Results

  await Promise.all(
    widget.particles.flatMap(async ({ address, type, series }) => {
      for (const current of series) {
        mapping[current.name] = []
      }

      let currentTimestamp = start
      while (true) {
        const particles = await engine.particles.getAll({
          address,
          type,
          after: currentTimestamp.toISOString(),
          before: end?.toISOString(),
          timespan: widget.timespan,
          limit: 5000,
        })

        if (particles.length === 0) {
          break
        }

        currentTimestamp = moment.utc(particles[particles.length - 1].timestamp).add(1, 'ms')

        series.map((series) => {
          mapping[series.name].push(
            ...particles.flatMap((particle) => {
              if (series.field == null) {
                return []
              }

              const timestamp = particle.timestamp
              let value = particle.data[series.field]
              if (typeof value !== 'number' && typeof value !== 'string') {
                if (typeof value === 'boolean') {
                  return [[timestamp, value as any as number]]
                }

                return []
              }

              return [[timestamp, value]]
            })
          )
        })
      }
    })
  )

  return mapping
}

watch(
  [() => JSON.stringify(widget.particles), () => [widget.after, widget.before, widget.timespan]],
  () => {
    loading = true
  }
)

watch(
  [
    debouncedComputed(() => JSON.stringify(widget.particles), 1000),
    debouncedComputed(() => [widget.after, widget.before, widget.timespan], 250),
  ],
  async () => {
    loading = true
    try {
      streamedData = {}
      data = await getData()
      for (const key of Object.keys(data)) {
        data[key].push(...(streamedData[key] ?? []))
      }
      streamedData = {}
    } finally {
      loading = false
    }
  },
  { immediate: true }
)

function prune() {
  for (const key of Object.keys(data)) {
    const values = data[key]
    let i = 0
    while (values.length > 0) {
      const [timestamp] = values[i]
      if (moment.utc(timestamp as string).isSameOrAfter(start)) {
        break
      }

      i++
    }

    if (i > 0) {
      data[key] = values.slice(i)
    }
  }
}

client.useStream({
  stream: computed(() =>
    widget.particles.map((particle, i) => ({
      id: String(i),
      path: '/api/particles',
      query: {
        address: particle.address,
        type: particle.type,
      },
    }))
  ),
  parse: ParticleModel as any,
  onReceive: (particle: Particle, stream: Stream) => {
    if (
      moment.utc(particle.timestamp).isBefore(start) ||
      (end != null && moment.utc(particle.timestamp).isSameOrAfter(end))
    ) {
      return
    }

    const particleIndex = Number(stream.id)
    const definition = widget.particles[particleIndex]
    const output = loading ? streamedData : data

    appended++
    if (appended > 5) {
      appended = 0
      prune()
    }

    for (const series of definition.series) {
      if (series.field == null) {
        continue
      }

      if (output[series.name] == null) {
        output[series.name] = []
      }

      let value = particle.data[series.field]
      if (typeof value !== 'number' && typeof value !== 'string') {
        if (typeof value === 'boolean') {
          output[series.name].push([particle.timestamp, value as any as number])
        }
      } else {
        output[series.name].push([particle.timestamp, value])
      }
    }
  },
})

const series = $computed(() => {
  return widget.particles.flatMap((particle) =>
    particle.series.map((series) => {
      return {
        animation: false,
        name: series.name,
        data: data[series.name],
        type: widget.display,
        showSymbol: false,
        symbolSize: 3,
        hoverAnimation: false,
        // animation: widget.display === 'bar' ? false : true,
        large: true,
        sampling: 'minmax' as any,
      }
    })
  )
})

const option: Option = $computed(() => {
  return {
    hoverAnimation: false,
    legend: { show: true },
    tooltip: { trigger: 'axis' },
    dataZoom: [{ type: 'inside' }],
    xAxis: {
      name: 'Time',
      type: 'time',
      startValue: bounds.start,
      endValue: bounds.end,
    },
    yAxis: {
      name: widget.unit ?? '',
    },
    series,
  }
})
</script>

<template>
  <chart ref="instance" height="100px" :loading="loading" :option="option" />
</template>
