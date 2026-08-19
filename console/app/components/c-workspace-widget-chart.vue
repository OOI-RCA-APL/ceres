<script lang="ts" setup>
import { useIntervalFn } from '@vueuse/core'
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

// What each series holds, owned here rather than read back from the chart, whose own copy an
// option rebuild replaces. Plain arrays, off the reactive graph, since a record arriving must
// redraw two lines and not rebuild the option around them.
const plotted: Data = {}

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

  plotted[seriesName] ??= []
  plotted[seriesName].push(...entries)
}

/** Draw what `names` hold, or every series when no names are given.

One partial application per batch, carrying only ids and data, so a tick costs one draw however
many series received records, and none of the option around them is rebuilt.
*/
function draw(names?: string[]) {
  const series = (names ?? Object.keys(plotted)).flatMap((name) => {
    const id = seriesIds[name]
    return id == null ? [] : [{ id, data: plotted[name] ?? [] }]
  })

  if (series.length > 0) {
    instance?.setOption({ series })
  }
}

const seriesIds = $computed(() => {
  const ids = {} as Record<string, string>
  for (const particle of widget.particles) {
    for (const [index, series] of particle.series.entries()) {
      ids[getSeriesName(series, index)] = series.id
    }
  }

  return ids
})

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
      // Both fits let the maximum hug the data. From-zero extends only the minimum to
      // zero, so all-negative data still spans its own extent.
      scale: true,
      min: (value: { min: number }) =>
        widget.fit === 'from-zero' ? Math.min(0, value.min) : value.min,
      inverse: widget.flipY,
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

/** Everything about the series except what they hold.

The records belong to the chart, which `load` and the arriving stream write into directly. Naming
`data` here would carry a copy taken when this was last built, and the option is applied a frame
later, so each rebuild would put back a list from before the records that arrived in between.
*/
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
        ...animation,
        showSymbol: false, // Disable showing dots, for performance.
        symbolSize: 3,
        emphasis: {
          scale: false, // Disable showing dot on hover.
        } as any,
        large: true, // Enable large data set optimization.
        largeThreshold: 1,
        // Drawn at the resolution of the axis rather than of the feed, which at a hundred
        // records a second puts thousands of them on the same column of pixels. The shape is
        // kept, peaks included, rather than thinned by taking every nth record.
        sampling: 'lttb',
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
        plotted[name] = [...entries]
      }

      draw(Object.keys(data))
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
  const arrived: string[] = []
  for (const name in pending) {
    if (pending[name]!.length > 0) {
      append(name, pending[name]!, 'instance')
      arrived.push(name)
    }
  }

  clearPending()
  if (arrived.length > 0) {
    draw(arrived)
  }

  lastPendingApplied = time.now
}

const pendingApplyInterval = duration(0.5, 'seconds')

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

// Compared as text rather than as a fresh array, which is a new object on every read and so
// reports a change whenever anything touches the widget, reloading a chart that never moved and
// discarding the records waiting to be drawn.
const windowKey = $computed(() => `${widget.after ?? ''}|${widget.timespan ?? ''}`)

watch([() => JSON.stringify(widget.particles), () => windowKey], () => {
  isLoading = true
})

watch(
  [
    () => instance,
    () => isInitialized,
    debouncedComputed(() => JSON.stringify(widget.particles), 1000),
    debouncedComputed(() => windowKey, 250),
  ],
  async () => {
    // Nothing to load into yet. The flag starts set, and leaving it that way here would hold off
    // every later batch of records, since applying them waits on the load being finished.
    if (instance == null || !isInitialized) {
      isLoading = false
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

// Records older than the window are dropped rather than left to grow without bound, the chart
// being open for as long as the workspace is.
function prune() {
  const dropped: string[] = []
  for (const name in plotted) {
    const data = plotted[name]!
    let index = 0
    while (index < data.length && utc(data[index]![0]).isBefore(start)) {
      index++
    }

    if (index > 0) {
      plotted[name] = data.slice(index)
      dropped.push(name)
    }
  }

  if (dropped.length > 0) {
    draw(dropped)
  }
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
