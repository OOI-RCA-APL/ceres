<script lang="ts" setup>
import { useIntervalFn } from '@vueuse/core'
import moment from 'moment'
import { watchEffect, computed, watch } from 'vue'

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

let instance = $shallowRef<InstanceType<typeof Chart> | null>(null)
let isInitialized = $ref(false)
let isLoading = $ref(true)
let pending: Data = $ref({})

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

function append(seriesName: string, values: DataValue[][], to?: 'option' | 'pending' | 'instance') {
  if (to == null) {
    to = isZooming ? 'option' : 'instance'
  }

  if (to === 'option') {
    if (instance == null) {
      return
    }
    const option = instance.getOption() as Option
    const seriess =
      option.series == null || Array.isArray(option.series) ? option.series ?? [] : [option.series]
    const series = seriess.find((current) => current.name === seriesName)
    if (series == null) {
      return
    }

    let data = series.data as DataValue[][]
    if (!Array.isArray(series.data)) {
      series.data = data = []
    }

    data.push(...values)
    instance.setOption({ series: option.series })
  } else if (to === 'pending') {
    pending[seriesName] ??= []
    pending[seriesName].push(...values)
  } else {
    const seriesIndex = seriesIndexes[seriesName] ?? null
    if (seriesIndex == null) {
      console.error(`Append data series ${seriesName} not found.`)
      return
    }

    try {
      if (instance != null) {
        instance.appendData({ seriesIndex, data: values })
      }
    } catch (error) {
      console.error(`Append data series index ${seriesIndex} not found internally.`)
    }
  }
}

const seriesIndexes = $computed(() => {
  const indexes = {} as Record<string, number>
  let i = 0
  for (const particle of widget.particles) {
    for (const series of particle.series) {
      indexes[series.name] = i++
    }
  }

  return indexes
})

let isZooming = $ref(false)

watchEffect((cleanup) => {
  instance?.on('dataZoom', (incoming: any) => {
    for (const event of incoming.batch) {
      if (event.start !== 0 || event.end !== 100) {
        isZooming = true
        return
      }
    }

    isZooming = false
  })

  cleanup(() => {
    instance?.off('dataZoom')
  })
})

const xMin = $computed(() => start.valueOf())
const xMax = $computed(() => (end ?? time.now).valueOf())

const axisOption: Option = $computed(() => {
  // Expand the actual x-axis range slightly to avoid flickering between interval scales when new
  // data is appended and the `duration` is a boundary value such as one hour.
  return {
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'filter' }],
    xAxis: {
      name: 'Time',
      type: 'time',
      min: xMin,
      max: xMax,
    },
    yAxis: {
      name: widget.unit ?? '',
      type: 'value',
    },
  }
})

const baseAxisOption = axisOption
const baseOption: Option = $computed(() => {
  const series = widget.particles.flatMap((particle) =>
    particle.series.map((series) => {
      const result = {
        animation: false,
        name: series.name,
        type: widget.display,
        data: getData(series.name),
        showSymbol: false,
        symbolSize: 3,
        emphasis: {
          scale: false,
        } as any,
        large: true,
        largeThreshold: 100,
        sampling: 'minmax' as any,
      }

      return result
    })
  )

  return {
    animation: true,
    hoverAnimation: true,
    legend: { show: true },
    tooltip: { trigger: 'axis' },
    series,
    ...baseAxisOption,
  }
})

watch([() => instance, () => baseOption], () => {
  if (instance) {
    requestAnimationFrame(() => {
      if (instance) {
        instance.setOption(baseOption, {
          withDefaults: true,
        })

        isInitialized = true
      }
    })
  } else {
    isInitialized = false
  }
})

watch([() => instance, () => axisOption], () => {
  setTimeout(() => {
    if (instance) {
      instance?.setOption(axisOption)
    }
  }, 0)
})

async function load() {
  await Promise.all(
    widget.particles.map(async ({ address, type, series }) => {
      const data = {} as Data
      let timestamp = start
      while (instance != null) {
        const particles = await engine.particles.getAll(
          {
            address,
            type,
            after: timestamp.toISOString(),
            before: end?.toISOString(),
            timespan: widget.timespan,
            limit: 5000,
          },
          { cache: 1000 }
        )

        if (particles.length === 0) {
          break
        }

        timestamp = moment.utc(particles[particles.length - 1].timestamp).add(1, 'ms')

        for (const { name, field } of series) {
          if (field == null) {
            continue
          }

          for (const particle of particles) {
            const timestamp = particle.timestamp
            const value = particle.data[field]
            if (
              typeof value === 'number' ||
              typeof value === 'string' ||
              typeof value === 'boolean'
            ) {
              data[name] ??= []
              data[name].push([timestamp, value as any])
            }
          }
        }
      }

      for (const [name, values] of Object.entries(data)) {
        clear(name)
        append(name, values, 'instance')
      }
    })
  )
}

function clearPending() {
  pending = {}
}

function applyPending() {
  for (const [name, values] of Object.entries(pending)) {
    append(name, values)
  }

  pending = {}
}

watch(
  [() => JSON.stringify(widget.particles), () => [widget.after, widget.before, widget.timespan]],
  () => {
    isLoading = true
  }
)

watch(
  [
    () => instance,
    () => isInitialized,
    debouncedComputed(() => JSON.stringify(widget.particles), 1000),
    debouncedComputed(() => [widget.after, widget.before, widget.timespan], 250),
  ],
  async () => {
    if (instance == null || !isInitialized) {
      return
    }

    isLoading = true
    try {
      clearPending()
      await load()
      applyPending()
    } finally {
      isLoading = false
    }
  },
  { immediate: true }
)

function clear(seriesName?: string) {
  const option = instance?.getOption()
  if (option == null) {
    return
  }

  const series =
    option.series == null || Array.isArray(option.series) ? option.series ?? [] : [option.series]

  for (const current of series) {
    if (seriesName == null || current.name !== seriesName) {
      continue
    }

    const data = current.data as any[][] | undefined
    if (data != null) {
      data.length = 0
    }
  }

  instance?.setOption({ series: option.series })
}

function getData(seriesName: string) {
  const option = instance?.getOption()
  if (option == null) {
    return []
  }

  const series =
    option.series == null || Array.isArray(option.series) ? option.series ?? [] : [option.series]

  for (const current of series) {
    if (current.name === seriesName) {
      return current.data as any[][] | undefined
    }
  }

  return []
}

function prune() {
  const option = instance?.getOption()
  if (option == null) {
    return
  }

  const series =
    option.series == null || Array.isArray(option.series) ? option.series ?? [] : [option.series]

  for (const current of series) {
    const data = current.data as any[][] | undefined
    if (data == null) {
      continue
    }

    let i = 0
    while (data.length > 0) {
      const [timestamp] = data[i]
      if (moment.utc(timestamp).isSameOrAfter(start)) {
        break
      }

      i++
    }

    if (i > 0) {
      current.data = data.slice(i)
    }
  }

  instance?.setOption({ series: option.series })
}

useIntervalFn(() => {
  prune()
}, 10000)

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
    if (instance == null) {
      return
    }

    if (!isLoading) {
      applyPending()
    }

    if (
      moment.utc(particle.timestamp).isBefore(start) ||
      (end != null && moment.utc(particle.timestamp).isSameOrAfter(end))
    ) {
      return
    }

    const particleIndex = Number(stream.id)
    const particleDefinition = widget.particles[particleIndex] ?? null
    if (particleDefinition == null) {
      return
    }

    for (const series of particleDefinition.series) {
      if (series.field == null) {
        continue
      }

      let value = particle.data[series.field]
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        const entry = [particle.timestamp, value as any]
        append(series.name, [entry], isLoading ? 'pending' : undefined)
      }
    }
  },
})
</script>

<template>
  <chart ref="instance" height="100px" :loading="isLoading" />
</template>
