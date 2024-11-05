<script lang="ts" setup>
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

type Data = Record<string, DataValue[][]>

const data: Data = {} // Not reactive for performance.
let appendedData: Data = {} // Not reactive for performance.
let appendedCount = $ref(0)
let isLoading = $ref(true)

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

// Actual x-axis min value for the chart.
const minXValue = $computed(() => {
  const current = moment.utc(start)
  // Expand the actual x-axis range slightly to avoid flickering between interval scales when new
  // data is appended and the `duration` is a boundary value such as one hour.
  return current.subtract(duration.asMilliseconds() / 2000, 'ms').valueOf()
})

async function fetchData() {
  for (const particle of widget.particles) {
    for (const current of particle.series) {
      data[current.name] ??= []
    }
  }

  const output = {} as Data

  await Promise.all(
    widget.particles.flatMap(async ({ address, type, series }) => {
      for (const current of series) {
        output[current.name] ??= []
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

        for (const { name, field } of series) {
          output[name] ??= []
          output[name].push(
            ...particles.flatMap((particle) => {
              if (field == null) {
                return []
              }

              const timestamp = particle.timestamp
              const value = particle.data[field]
              if (
                typeof value === 'number' ||
                typeof value === 'string' ||
                typeof value === 'boolean'
              ) {
                return [[timestamp, value as any]]
              }

              return []
            })
          )
        }
      }
    })
  )

  for (const values of Object.values(data)) {
    values.length = 0
  }

  for (const [name, values] of Object.entries(output)) {
    data[name] ??= []
    data[name].push(...values)
  }
}

watch(
  [() => JSON.stringify(widget.particles), () => [widget.after, widget.before, widget.timespan]],
  () => {
    isLoading = true
  }
)

watch(
  [
    debouncedComputed(() => JSON.stringify(widget.particles), 1000),
    debouncedComputed(() => [widget.after, widget.before, widget.timespan], 250),
  ],
  async () => {
    isLoading = true
    try {
      appendedData = {}
      await fetchData()
      for (const key of Object.keys(data)) {
        data[key].push(...(appendedData[key] ?? []))
      }
      appendedData = {}
    } finally {
      isLoading = false
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
    const output = isLoading ? appendedData : data

    appendedCount++
    if (appendedCount > 250) {
      appendedCount = 0
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
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        output[series.name].push([particle.timestamp, value as any])
      }
    }
  },
})

const series = $computed(() => {
  return widget.particles.flatMap((particle) =>
    particle.series.map((series) => {
      const values = (data[series.name] ??= [])
      return {
        animation: true,
        name: series.name,
        data: values,
        type: widget.display,
        showSymbol: false,
        symbolSize: 3,
        emphasis: {
          scale: false,
        } as any,
        large: true,
        sampling: 'lttb' as any,
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
      startValue: minXValue,
    },
    yAxis: {
      name: widget.unit ?? '',
    },
    series,
  }
})
</script>

<template>
  <chart height="100px" :loading="isLoading" :option="option" />
</template>
