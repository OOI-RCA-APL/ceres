<script lang="ts" setup>
import { useElementVisibility, useIntervalFn } from '@vueuse/core'
import { computed, watch, watchEffect } from 'vue'

import { useClient } from '@/api/client'
import type { Stream } from '@/api/client'
import { useEngine } from '@/api/engine'
import { ParticleModel } from '@/api/particles'
import type { Particle } from '@/api/particles'
import { chartPalette } from '@/chart'
import type { DataValue, Option } from '@/chart'
import CChart from '@/components/c-chart.vue'
import icons from '@/icons'
import { useDerivedChartUnit } from '@/particle-types'
import { usePreferences } from '@/preferences'
import { duration, useTime, utc, parseDuration } from '@/time'
import { debouncedComputed, toTitle } from '@/utilities'
import { useWorkspace } from '@/workspace'
import type { ChartWidget, ChartWidgetSeries } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()
const client = useClient()
const time = useTime()
const workspace = useWorkspace()
const preferences = usePreferences()

type DataEntry = [number, DataValue]
type Data = Record<string, DataEntry[]>

let instance = $shallowRef<InstanceType<typeof CChart> | null>(null)
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
    return
  }

  // Written through the option rather than `appendData`, which lands the records in the series
  // store without redrawing the line, leaving a chart that reports the data it never plots.
  const option = instance?.getOption()
  if (option == null) {
    return
  }

  const series = getSeries(option)
  const target = series.find((current) => current.name === seriesName)
  if (target == null) {
    console.error(`Append data series ${seriesName} not found.`)
    return
  }

  const data = (target.data ??= []) as DataEntry[]
  data.push(...entries)
  instance?.setOption({ series })
}

const xMin = $computed(() => (isPaused ? frozenXMin : start.valueOf()))
const xMax = $computed(() => (isPaused ? frozenXMax : (end ?? time.now).valueOf()))

const derivedUnit = $(useDerivedChartUnit(() => widget, workspace).unit)

/** The Y axis unit, from the setting or derived from the plotted fields' declared units. */
const unit = $computed(() => widget.unit?.trim() || derivedUnit)

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

/** The color each series is drawn in, in the flat order the chart draws them.

Resolved apart from the data, `chartPalette` reading computed styles and the option around it
being rebuilt on every record that arrives. A series carries a color only once one has been
chosen for it, so the rest follow the color mode rather than whichever mode they were added in.
*/
const seriesColors = $computed(() => {
  // The palette is read off the document, so the mode is what says to read it again.
  void preferences.isDarkModeEnabled
  const palette = chartPalette().series
  return widget.particles
    .flatMap((particle) => particle.series)
    .map((series, index) => series.color ?? palette[index % palette.length] ?? palette[0]!)
})

const baseAxisOption = $computed(() => axisOption)
const baseOption: Option = $computed(() => {
  // Counted across every particle entry rather than within one, the chart drawing them as a
  // single run.
  let position = 0
  const series = widget.particles.flatMap((particle) =>
    particle.series.map((series, index) => {
      const name = getSeriesName(series, index)
      const color = seriesColors[position]
      position += 1
      const result = {
        // The stable ID is what `replaceMerge` matches on, keeping surviving series merged
        // in place rather than recreated.
        id: series.id,
        name,
        type: widget.display,
        itemStyle: { color },
        lineStyle: { color },
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
    }),
  )

  return {
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter(params: any) {
        if (!Array.isArray(params)) {
          params = [params]
        }
        if (params.length === 0) {
          return ''
        }

        const header = utc(params[0].value[0]).format('YYYY-MM-DD HH:mm:ss.SSS') + ' UTC'
        const lines = params.map(
          (p: any) =>
            `${p.marker} ${p.seriesName}: <strong>${p.value[1]}${unit ? ' ' + unit : ''}</strong>`,
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
    // Zoom state belongs to the instance, so losing it also drops the pause.
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
        const particles = await engine.particles.getAll({
          address: workspace.resolveAddress(address),
          type,
          after: widget.after,
          timespan: widget.timespan ?? '1h',
          subsample: 5000,
          limit: 5000,
        })

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
    }),
  )
}

function clearPending() {
  for (const name in pending) {
    pending[name]!.length = 0
  }
}

let lastPendingApplied = $shallowRef(time.now)

function applyPending() {
  for (const name in pending) {
    append(name, pending[name]!, 'instance')
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

// What arrived out of view goes in the moment the chart is back, rather than waiting out the
// interval a hidden chart falls back to, which would leave a minute of records unplotted.
watch(
  () => isVisible,
  (visible) => {
    if (visible && !isPaused && !isLoading) {
      applyPending()
    }
  },
)

watch(
  () => time.now,
  () => {
    if (isLoading) {
      return
    }

    if (!isPaused && time.now.diff(lastPendingApplied) >= pendingApplyInterval.asMilliseconds()) {
      applyPending()
    }
  },
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
  { immediate: true },
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
      const [timestamp] = data[i]!
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
    })),
  ),
  parse: ParticleModel,
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
  <div class="relative h-25">
    <c-chart
      ref="instance"
      class="h-full w-full"
      :class="(isLoading || isJustLoaded) && 'pointer-events-none'"
      height="100%"
      :loading="isLoading"
    />
    <c-button
      class="absolute top-1 right-0 z-1"
      color="primary"
      :icon="isPaused ? icons.start : icons.pause"
      size="sm"
      square
      variant="ghost"
      @click="togglePause"
    />
  </div>
</template>
