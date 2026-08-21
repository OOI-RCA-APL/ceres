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
import { debouncedComputed, formatNumber, toTitle } from '@/utilities'
import { useWorkspace } from '@/workspace'
import type { ChartWidget, ChartWidgetParticle, ChartWidgetSeries } from '@/workspace'

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

/** The extent across every plotted series, whatever the legend hides.

Held rather than derived, the axis asking for it on every render and a full sweep of the
records being far too much to spend there. Folded forward as records arrive and recomputed
only where they are replaced or dropped.
*/
let allExtent = $shallowRef<{ min: number; max: number } | null>(null)

function foldExtent(entries: DataEntry[]) {
  let extent = allExtent
  for (const [, value] of entries) {
    const current = Number(value)
    if (!Number.isFinite(current)) {
      continue
    }

    extent =
      extent == null
        ? { min: current, max: current }
        : { min: Math.min(extent.min, current), max: Math.max(extent.max, current) }
  }

  allExtent = extent
}

function recomputeExtent() {
  allExtent = null
  for (const id in plotted) {
    foldExtent(plotted[id]!)
  }
}

/** The connections found producing each undeclared group's type, by `address|type`.

The fallback for a type declaring no connections, where only an unfiltered load reveals
what its records carry. A type one connection produces is never split and costs no extra
query.
*/
const splitConnections = $ref<Record<string, string[]>>({})

function groupKey(particle: ChartWidgetParticle): string {
  return `${particle.address?.toString() ?? ''}|${particle.type ?? ''}`
}

/** The connections the group's type declares its records carry, deciding the split before
any records load. */
function declaredConnections(particle: ChartWidgetParticle): string[] {
  const address = workspace.resolveAddress(particle.address)
  if (address == null || particle.type == null) {
    return []
  }

  return (
    engine.components.get(address.toString())?.particles.find((type) => type.type === particle.type)
      ?.connections ?? []
  )
}

/** The connections a group draws a line each for, empty where it draws one line for all. */
function splitFor(particle: ChartWidgetParticle): string[] {
  if (particle.connection != null) {
    return []
  }

  const declared = declaredConnections(particle)
  const found = declared.length > 0 ? declared : (splitConnections[groupKey(particle)] ?? [])
  return found.length > 1 ? found : []
}

/** What one drawn line is keyed by, a split group qualifying its series by connection. */
function lineId(series: ChartWidgetSeries, connection: string | null): string {
  return connection == null ? series.id : `${series.id}|${connection}`
}

/** Every line the chart currently draws, which is what may be written into. */
const drawnIds = $computed(() => {
  const ids = new Set<string>()
  for (const particle of widget.particles) {
    const connections = splitFor(particle)
    for (const series of particle.series) {
      for (const connection of connections.length > 0 ? connections : [null]) {
        ids.add(lineId(series, connection))
      }
    }
  }

  return ids
})

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

// Keyed by series ID rather than by the name on screen, two groups of the same type differing
// only by connection drawing two lines that would otherwise share a name and a bucket.
function append(seriesId: string, entries: DataEntry[], to: 'pending' | 'instance') {
  if (entries.length === 0) {
    return
  }

  if (to === 'pending') {
    pending[seriesId] ??= []
    pending[seriesId].push(...entries)
    return
  }

  plotted[seriesId] ??= []
  plotted[seriesId].push(...entries)
  foldExtent(entries)
}

/** Draw what `ids` hold, or every line when none are given.

One partial application per batch, carrying only ids and data, so a tick costs one draw however
many lines received records, and none of the option around them is rebuilt. Lines the option no
longer carries are dropped, since a group splitting by connection retires the one it drew for
all of them and writing into a series that is gone is an error.
*/
function draw(ids?: string[]) {
  const series = (ids ?? Object.keys(plotted))
    .filter((id) => drawnIds.has(id))
    .map((id) => ({ id, data: plotted[id] ?? [] }))

  if (series.length > 0) {
    instance?.setOption({ series })
  }
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
      axisLabel: {
        formatter: (value: number) => formatNumber(value, widget.decimals),
      },
      scale: true,
      // Shown fits whatever the legend leaves on, which is the extent the axis is handed.
      // All reaches past it to the series switched off, holding the axis still as they go.
      min: (value: { min: number }) => {
        const base =
          widget.fit === 'all' ? Math.min(value.min, allExtent?.min ?? value.min) : value.min
        // Zero extends the minimum alone, so all-negative data still spans its own extent.
        return widget.fromZero ? Math.min(0, base) : base
      },
      max: (value: { max: number }) =>
        widget.fit === 'all' ? Math.max(value.max, allExtent?.max ?? value.max) : value.max,
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

  // A chosen color stands for one line, so a split group takes the palette instead rather than
  // drawing every one of its connections in the same color.
  const colors: Record<string, string> = {}
  let position = 0
  for (const particle of widget.particles) {
    const connections = splitFor(particle)
    for (const series of particle.series) {
      for (const connection of connections.length > 0 ? connections : [null]) {
        const fallback = palette[position % palette.length] ?? palette[0]!
        colors[lineId(series, connection)] =
          connections.length > 0 ? fallback : (series.color ?? fallback)
        position += 1
      }
    }
  }

  return colors
})

const baseAxisOption = $computed(() => axisOption)

/** Everything about the series except what they hold.

The records belong to the chart, which `load` and the arriving stream write into directly. Naming
`data` here would carry a copy taken when this was last built, and the option is applied a frame
later, so each rebuild would put back a list from before the records that arrived in between.
*/
const baseOption: Option = $computed(() => {
  const series = widget.particles.flatMap((particle) => {
    const connections = splitFor(particle)
    return particle.series.flatMap((series, index) =>
      (connections.length > 0 ? connections : [null]).map((connection) => {
        const base = getSeriesName(series, index)
        const name = connection == null ? base : `${base} (${connection})`
        const color = seriesColors[lineId(series, connection)]
        const result = {
          // The stable ID is what `replaceMerge` matches on, keeping surviving series merged
          // in place rather than recreated.
          id: lineId(series, connection),
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
  })

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
        const lines = params.map((p: any) => {
          const value = p.value[1]
          const read = typeof value === 'number' ? formatNumber(value, widget.decimals) : value
          return `${p.marker} ${p.seriesName}: <strong>${read}${unit ? ' ' + unit : ''}</strong>`
        })
        return `${header}<br/>${lines.join('<br/>')}`
      },
    },
    // Counted over the lines drawn rather than the series configured, a group split by
    // connection standing for one series and several lines.
    legend: { show: series.length > 1 },
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

async function fetchParticles(particle: ChartWidgetParticle, connection: string | null) {
  return await engine.particles.getAll({
    address: workspace.resolveAddress(particle.address),
    type: particle.type,
    connection,
    after: widget.after,
    timespan: widget.timespan ?? '1h',
    // Subsampling buckets by time and keeps one record per bucket, so a query covering several
    // connections would thin them against each other. One query per drawn line keeps each whole.
    subsample: 5000,
    limit: 5000,
  })
}

function collect(
  data: Data,
  particles: Particle[],
  group: ChartWidgetParticle,
  key: string | null,
) {
  for (const current of group.series) {
    const field = current.field
    if (field == null) {
      continue
    }

    for (const particle of particles) {
      const value = particle.data[field]
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        const bucket = (data[lineId(current, key)] ??= [])
        bucket.push([utc(particle.timestamp).valueOf(), value as any])
      }
    }
  }
}

async function load() {
  await Promise.all(
    widget.particles.map(async (group) => {
      const data = {} as Data
      if (instance != null) {
        const known = splitFor(group)
        if (known.length > 0) {
          const results = await Promise.all(
            known.map(async (connection) => [connection, await fetchParticles(group, connection)]),
          )
          for (const [connection, particles] of results as [string, Particle[]][]) {
            collect(data, particles, group, connection)
          }
        } else {
          const particles = await fetchParticles(group, group.connection ?? null)

          // What the records themselves say produced this type, only for a type declaring
          // nothing, since `splitFor` answers from the declaration otherwise and a split
          // decided here would draw lines it does not expect.
          const discovering = group.connection == null && declaredConnections(group).length === 0
          const found = discovering
            ? [
                ...new Set(
                  particles.map((particle) => particle.connection).filter((name) => name != null),
                ),
              ].sort()
            : []

          if (discovering) {
            splitConnections[groupKey(group)] = found
          }

          if (found.length > 1) {
            // These records came thinned against each other, so they are dropped rather than
            // drawn, and each connection is asked for on its own.
            for (const series of group.series) {
              plotted[series.id] = []
            }

            const results = await Promise.all(
              found.map(async (connection) => [
                connection,
                await fetchParticles(group, connection),
              ]),
            )
            for (const [connection, records] of results as [string, Particle[]][]) {
              collect(data, records, group, connection)
            }
          } else {
            collect(data, particles, group, null)
          }
        }
      }

      for (const [id, entries] of Object.entries(data)) {
        plotted[id] = [...entries]
      }

      recomputeExtent()
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
    recomputeExtent()
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
        connection: particle.connection,
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

    // A split group has a line per connection, so the record joins the one it came in on. Its
    // own connection is unset only where the group is not split.
    const connections = splitFor(particleDefinition)
    const key =
      connections.length > 0 &&
      particle.connection != null &&
      connections.includes(particle.connection)
        ? particle.connection
        : null
    if (connections.length > 0 && key == null) {
      return
    }

    for (const series of particleDefinition.series) {
      if (series.field == null) {
        continue
      }

      const value = particle.data[series.field]
      if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
        const entry: DataEntry = [utc(particle.timestamp).valueOf(), value as any]
        append(lineId(series, key), [entry], 'pending')
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
