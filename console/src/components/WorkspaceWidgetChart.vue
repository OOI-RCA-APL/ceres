<script lang="ts" setup>
import { useIntervalFn } from '@vueuse/core'
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

type Results = Record<string, DataValue[][]>
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

const queryKey = debouncedComputed(() => [JSON.stringify(widget.particles)], 1000)

let data: Results = {}
let streamedData: Results = {}
let isGettingData = $ref(false)

watch(
  () => [queryKey, widget.after, widget.before, widget.timespan],
  async () => {
    isGettingData = true
    try {
      streamedData = {}
      data = await getData()
      for (const key of Object.keys(data)) {
        data[key].push(...(streamedData[key] ?? []))
      }
      streamedData = {}
    } finally {
      isGettingData = false
    }
  },
  { immediate: true }
)

function pruneResults() {
  if (isGettingData) {
    return
  }

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

useIntervalFn(() => {
  pruneResults()
}, 50)

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

    const definition = widget.particles[Number(stream.id)]
    const timestamp = particle.timestamp
    const appendedResults = isGettingData ? data : data

    for (const series of definition.series) {
      if (series.field == null) {
        continue
      }

      if (appendedResults[series.name] == null) {
        appendedResults[series.name] = []
      }

      let value = particle.data[series.field]
      if (typeof value !== 'number' && typeof value !== 'string') {
        if (typeof value === 'boolean') {
          appendedResults[series.name].push([timestamp, value as any as number])
        }
      } else {
        appendedResults[series.name].push([timestamp, value])
      }
    }
  },
})

const option: Option = $computed(() => ({
  legend: { show: true },
  tooltip: { trigger: 'axis' },
  dataZoom: [{ type: 'inside' }],
  xAxis: {
    name: 'Time',
    type: 'time',
    startValue: Number(start.toDate()),
    // endValue: end.toISOString(),
  },
  yAxis: {
    name: widget.unit ?? '',
  },
  series: widget.particles.flatMap((particle) =>
    particle.series.map((series) => ({
      name: series.name,
      data: data[series.name],
      type: widget.display,
      showSymbol: false,
      symbolSize: 6,
    }))
  ),
}))
</script>

<template>
  <chart height="100px" :option="option" />
</template>
