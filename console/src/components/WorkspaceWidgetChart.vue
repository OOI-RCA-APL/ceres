<script lang="ts" setup>
import { useElementVisibility, useIntervalFn } from '@vueuse/core'
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

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()
const client = useClient()
const time = useTime()

type DataEntry = [string, DataValue]
type Data = Record<string, DataEntry[]>

let instance = $shallowRef<InstanceType<typeof Chart> | null>(null)
let isInitialized = $ref(false)
let isLoading = $ref(true)
const pending: Data = $ref({})

const start = $computed(() => {
  if (widget.after != null) {
    return moment.utc(widget.after)
  }

  const timespan = parseDuration(widget.timespan ?? '1h')
  return moment.utc(time.now).subtract(timespan)
})

const end = $computed(() => {
  if (widget.after != null) {
    const timespan = parseDuration(widget.timespan ?? '1h')
    return moment.utc(widget.after).add(timespan)
  }

  return null
})

function append(seriesName: string, entries: DataEntry[], to: 'pending' | 'instance') {
  if (entries.length === 0) {
    return
  }

  if (to === 'pending') {
    pending[seriesName] ??= []
    pending[seriesName].push(...entries)
  } else {
    const seriesIndex = seriesIndexes[seriesName] ?? null
    if (seriesIndex == null) {
      console.error(`Append data series ${seriesName} not found.`)
      return
    }

    try {
      if (instance != null) {
        instance.appendData({ seriesIndex, data: entries })
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

const xMin = $computed(() => start.valueOf())
const xMax = $computed(() => (end ?? time.now).valueOf())

const axisOption: Option = $computed(() => {
  return {
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
        name: series.name,
        type: widget.display,
        data: getData(series.name),
        animation: widget.display === 'bar' ? false : true, // Disable animation for bar chart.
        showSymbol: false, // Disable showing dots, for performance.
        symbolSize: 3,
        emphasis: {
          scale: false, // Disable showing dot on hover.
        } as any,
        large: true, // Enable large data set optimization.
        largeThreshold: 100,
      }

      return result
    })
  )

  return {
    tooltip: { trigger: 'axis', confine: true },
    legend: { show: widget.particles.flatMap((particle) => particle.series).length > 1 },
    dataZoom: [{ type: 'inside' }],
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
      if (instance != null) {
        const particles = await engine.particles.getAll(
          {
            address,
            type,
            after: widget.after,
            timespan: widget.timespan ?? '1h',
            subsample: 5000,
            limit: 5000,
          },
          { cache: 1000 }
        )

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

      for (const [name, entries] of Object.entries(data)) {
        clear(name)
        append(name, entries, 'instance')
      }
    })
  )
}

function clearPending() {
  for (const name in pending) {
    pending[name].length = 0
  }
}

let lastPendingApplied = $shallowRef(time.now)

function applyPending() {
  for (const name in pending) {
    append(name, pending[name], 'instance')
  }

  clearPending()
  lastPendingApplied = time.now
}

const isVisible = $(useElementVisibility(() => instance?.getDom()))
const pendingApplyInterval = $computed(() => {
  if (isVisible) {
    return moment.duration(1, 'seconds')
  } else {
    return moment.duration(1, 'minute')
  }
})

watch(
  () => time.now,
  () => {
    if (isLoading) {
      return
    }

    if (moment.duration(time.now.diff(lastPendingApplied)) >= pendingApplyInterval) {
      applyPending()
    }
  }
)

watch([() => JSON.stringify(widget.particles), () => [widget.after, widget.timespan]], () => {
  isLoading = true
})

watch(
  [
    () => instance,
    () => isInitialized,
    debouncedComputed(() => JSON.stringify(widget.particles), 1000),
    debouncedComputed(() => [widget.after, widget.timespan], 250),
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

function getSeries(option: Option) {
  if (option.series == null) {
    return []
  }
  if (Array.isArray(option.series)) {
    return option.series
  }

  return [option.series]
}

function clear(seriesName?: string) {
  const option = instance?.getOption()
  if (option == null) {
    return
  }

  const series = getSeries(option)
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

  const series = getSeries(option)
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

  const series = getSeries(option)
  for (const current of series) {
    const data = current.data as any[][] | undefined
    if (data == null) {
      continue
    }

    let i = 0
    while (i < data.length) {
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

useIntervalFn(
  () => {
    prune()
  },
  () => moment.duration(1, 'minute').asMilliseconds()
)

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

      const value = particle.data[series.field]
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        const entry: DataEntry = [particle.timestamp, value as any]
        append(series.name, [entry], 'pending')
      }
    }
  },
})

let isJustLoaded = $ref(false)
watchEffect((cleanup) => {
  if (isLoading) {
    isJustLoaded = false
  } else {
    isJustLoaded = true
    const timeout = setTimeout(() => {
      isJustLoaded = false
    }, 100)
    cleanup(() => {
      clearTimeout(timeout)
    })
  }
})
</script>

<template>
  <chart
    ref="instance"
    :class="(isLoading || isJustLoaded) && $style.interactionDisabled"
    height="100px"
    :loading="isLoading"
  />
</template>

<style lang="scss" module>
.interactionDisabled {
  pointer-events: none;
}
</style>
