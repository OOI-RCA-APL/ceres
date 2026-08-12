<script lang="ts" setup>
import { useElementVisibility, useIntervalFn } from '@vueuse/core'
import { watchEffect, computed, watch } from 'vue'

import { useClient, Stream } from '@/api/client'
import { useEngine } from '@/api/engine'
import { ParticleModel, Particle } from '@/api/particles'
import { Option, DataValue } from '@/chart'
import Chart from '@/components/Chart.vue'
import { deriveChartUnit, useParticleTypesByAddress } from '@/particle-types'
import { duration, utc, useTime } from '@/time'
import { toTitle, debouncedComputed, parseDuration } from '@/utilities'
import { ChartWidget, ChartWidgetSeries, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()
const client = useClient()
const time = useTime()
const workspace = useWorkspace()

type DataEntry = [number, DataValue]
type Data = Record<string, DataEntry[]>

let instance = $shallowRef<InstanceType<typeof Chart> | null>(null)
let isInitialized = $ref(false)
let isLoading = $ref(true)
let isPaused = $ref(false)
let frozenXMin = $ref(0)
let frozenXMax = $ref(0)
const pending: Data = $ref({})

function togglePause() {
  if (!isPaused) {
    frozenXMin = start.valueOf()
    frozenXMax = (end ?? time.now).valueOf()
    isPaused = true
  } else {
    isPaused = false
    applyPending()
  }
}

const start = $computed(() => {
  if (widget.after != null) {
    return utc(widget.after)
  }

  const timespan = parseDuration(widget.timespan ?? '1h')
  return utc(time.now.valueOf()).subtract(timespan)
})

const end = $computed(() => {
  if (widget.after != null) {
    const timespan = parseDuration(widget.timespan ?? '1h')
    return utc(widget.after).add(timespan)
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
    for (const [j, series] of particle.series.entries()) {
      indexes[getSeriesName(series, j)] = i++
    }
  }

  return indexes
})

const xMin = $computed(() => (isPaused ? frozenXMin : start.valueOf()))
const xMax = $computed(() => (isPaused ? frozenXMax : (end ?? time.now).valueOf()))

const particleAddresses = $computed(() =>
  widget.particles.flatMap((particle) => {
    const resolved = workspace.resolveAddress(particle.address)?.toString()
    return resolved == null ? [] : [resolved]
  })
)

const declaredTypes = $(useParticleTypesByAddress(() => particleAddresses).types)

/** The Y axis unit, from the setting or derived from the plotted fields' declared units. */
const unit = $computed(() => {
  const explicit = widget.unit?.trim()
  if (explicit) {
    return explicit
  }

  return deriveChartUnit(
    widget.particles,
    (address) => workspace.resolveAddress(address)?.toString() ?? null,
    declaredTypes
  )
})

const smoothAnimations = {
  animation: true,
  animationDurationUpdate: 1000,
  animationEasingUpdate: 'linear',
  // This threshold needs to be set, otherwise most charts just will not animate.
  animationThreshold: 200000,
} as const

const animatedDisplays: (typeof widget.display)[] = ['line']
const isAnimated = $computed(() => animatedDisplays.includes(widget.display))
const animation = $computed(() => (isAnimated ? smoothAnimations : { animation: false }))

const axisOption: Option = $computed(() => {
  return {
    xAxis: {
      name: 'Time',
      type: 'time',
      min: xMin,
      max: xMax,
      // Smoothly scroll the X axis as time progresses.
      ...animation,
    },
    yAxis: {
      name: unit,
      type: 'value',
    },
  }
})

function getSeriesName(series: ChartWidgetSeries, index: number): string {
  if (series.label) {
    return series.label
  }
  if (series.field) {
    return toTitle(series.field)
  }

  return String(index + 1)
}

const baseAxisOption = axisOption
const baseOption: Option = $computed(() => {
  const series = widget.particles.flatMap((particle) =>
    particle.series.map((series, index) => {
      const name = getSeriesName(series, index)
      const result = {
        // The stable ID is what `replaceMerge` matches on, keeping surviving series merged
        // in place rather than recreated.
        id: series.id,
        name,
        type: widget.display,
        ...({ progressive: false } as any),
        data: getData(name),
        ...animation,
        showSymbol: false, // Disable showing dots, for performance.
        symbolSize: 3,
        emphasis: {
          scale: false, // Disable showing dot on hover.
        } as any,
        large: true, // Enable large data set optimization.
        largeThreshold: 1,
      }

      return result
    })
  )

  return {
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter(params: any) {
        if (!Array.isArray(params)) params = [params]
        if (params.length === 0) return ''
        const header = utc(params[0].value[0]).format('YYYY-MM-DD HH:mm:ss.SSS') + ' UTC'
        const lines = params.map(
          (p: any) =>
            `${p.marker} ${p.seriesName}: <strong>${p.value[1]}${unit ? ' ' + unit : ''}</strong>`
        )
        return `${header}<br/>${lines.join('<br/>')}`
      },
    },
    legend: { show: widget.particles.flatMap((particle) => particle.series).length > 1 },
    dataZoom: [{ type: 'inside', filterMode: 'none' }],
    series,
    ...baseAxisOption,
  }
})

watch([() => instance, () => baseOption], () => {
  if (instance) {
    requestAnimationFrame(() => {
      if (instance) {
        // Replace merge restarts every series, so it is reserved for removals, the one change
        // the default merge mode cannot express and the cause of ghost lines otherwise.
        const previousIds = getSeries(instance.getOption() ?? {}).map((series) => series.id)
        const nextIds = new Set(getSeries(baseOption).map((series) => series.id))
        const removed = previousIds.some((id) => !nextIds.has(id))
        instance.setOption(baseOption, {
          withDefaults: true,
          ...(removed ? { replaceMerge: ['series'] } : {}),
        })

        isInitialized = true
      }
    })
  } else {
    isInitialized = false
    // We should reset zoom when chart state changes.
    isPaused = false
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
            address: workspace.resolveAddress(address),
            type,
            after: widget.after,
            timespan: widget.timespan ?? '1h',
            subsample: 5000,
            limit: 5000,
          },
          { cache: 1000 }
        )

        for (const [i, current] of series.entries()) {
          const field = current.field
          const name = getSeriesName(current, i)
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
              data[name].push([utc(timestamp).valueOf(), value as any])
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
    return duration(0.5, 'seconds')
  } else {
    return duration(1, 'minute')
  }
})

watch(
  () => time.now,
  () => {
    if (isLoading) {
      return
    }

    if (!isPaused && time.now.diff(lastPendingApplied) >= pendingApplyInterval.asMilliseconds()) {
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

// Replace merge leaves null slots where removed series sat, so the list is filtered.
function getSeries(option: Option) {
  if (option.series == null) {
    return []
  }

  const list = Array.isArray(option.series) ? option.series : [option.series]
  return list.filter((series) => series != null)
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

  instance?.setOption({ series })
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
      if (utc(timestamp).isSameOrAfter(start)) {
        break
      }

      i++
    }

    if (i > 0) {
      current.data = data.slice(i)
    }
  }

  instance?.setOption({ series })
}

useIntervalFn(prune, () => duration(1, 'minute').asMilliseconds())

client.useStream({
  stream: computed(() =>
    widget.particles.map((particle, i) => ({
      id: String(i),
      path: '/api/particles',
      query: {
        address: workspace.resolveAddress(particle.address),
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
      utc(particle.timestamp).isBefore(start) ||
      (end != null && utc(particle.timestamp).isSameOrAfter(end))
    ) {
      return
    }

    const particleIndex = Number(stream.id)
    const particleDefinition = widget.particles[particleIndex] ?? null
    if (particleDefinition == null) {
      return
    }

    for (const [i, series] of particleDefinition.series.entries()) {
      const label = getSeriesName(series, i)
      if (series.field == null) {
        continue
      }

      const value = particle.data[series.field]
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        const entry: DataEntry = [utc(particle.timestamp).valueOf(), value as any]
        append(label, [entry], 'pending')
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
  <div :class="$style.container">
    <chart
      ref="instance"
      :class="[(isLoading || isJustLoaded) && $style.interactionDisabled, $style.chart]"
      height="100%"
      :loading="isLoading"
    />
    <q-btn
      :class="$style.pauseButton"
      color="primary"
      dense
      flat
      :icon="isPaused ? 'play_arrow' : 'pause'"
      round
      size="sm"
      @click="togglePause"
    />
  </div>
</template>

<style lang="scss" module>
.container {
  position: relative;
  height: 100px;
}

.chart {
  width: 100%;
  height: 100%;
}

.pauseButton {
  position: absolute;
  top: 4px;
  right: 0;
  z-index: 1;

  &:hover {
    opacity: 1;
  }
}

.interactionDisabled {
  pointer-events: none;
}
</style>
