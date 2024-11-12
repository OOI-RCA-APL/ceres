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

const { widget } = $defineProps<{
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

const duration = $computed(() => {
  return moment.duration((end ?? time.now).diff(start))
})

function append(seriesName: string, entries: DataEntry[], to?: 'option' | 'pending' | 'instance') {
  if (entries.length === 0) {
    return
  }

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

    let data = series.data as DataEntry[]
    if (!Array.isArray(series.data)) {
      series.data = data = []
    }

    data.push(...entries)
    instance.setOption({ series: option.series })
  } else if (to === 'pending') {
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

const zoom = $ref({ start: 0, end: 100 })
const isZooming = $computed(() => zoom.start > 0 || zoom.end < 100)

watchEffect((cleanup) => {
  instance?.on('dataZoom', (incoming: any) => {
    for (const event of incoming.batch) {
      zoom.start = event.start
      zoom.end = event.end
    }
  })

  cleanup(() => {
    instance?.off('dataZoom')
  })
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
    tooltip: { trigger: 'axis' },
    legend: { show: true },
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
      let currentTimestamp = start
      while (instance != null) {
        const particles = await engine.particles.getAll(
          {
            address,
            type,
            after: currentTimestamp.toISOString(),
            before: end?.toISOString(),
            timespan: widget.timespan,
            limit: 5000,
          },
          { cache: 1000 }
        )

        if (particles.length === 0) {
          break
        }

        currentTimestamp = moment.utc(particles[particles.length - 1].timestamp).add(1, 'ms')

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
    append(name, pending[name])
  }

  clearPending()
  lastPendingApplied = time.now
}

const isVisible = $(useElementVisibility(() => instance?.getDom()))
const pendingApplyInterval = $computed(() => {
  if (!isVisible) {
    return moment.duration(5, 'minutes')
  }

  const percentageVisible = (zoom.end - zoom.start) / 100
  const timeVisible = moment.duration(duration.asMilliseconds() * percentageVisible)
  if (timeVisible.asDays() >= 1) {
    return moment.duration(1, 'minutes')
  }
  if (timeVisible.asHours() >= 1) {
    return moment.duration(30, 'seconds')
  }
  if (timeVisible.asMinutes() >= 30) {
    return moment.duration(15, 'seconds')
  }
  if (timeVisible.asMinutes() >= 5) {
    return moment.duration(5, 'seconds')
  }

  return moment.duration(1, 'seconds')
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

useIntervalFn(
  () => {
    prune()
  },
  () => pendingApplyInterval.asMilliseconds() * 5
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
    }, 1000)
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
