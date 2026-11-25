<script lang="ts">
const defaultOptions = Object.freeze<Option>({
  animation: true,
  backgroundColor: 'transparent',
  yAxis: {
    nameLocation: 'end',
    nameGap: 8,
    splitArea: {
      show: true,
    },
    nameTextStyle: {
      align: 'left',
      verticalAlign: 'bottom',
    },
    axisLabel: {
      hideOverlap: true,
    },
  },
  xAxis: {
    nameLocation: 'middle',
    nameGap: 26,
    nameTextStyle: {
      align: 'right',
    },
    axisLabel: {
      hideOverlap: true,
    },
  },
  useUTC: true,
  // Paged rather than wrapped, so the legend keeps to the one row the grid reserves for it below
  // instead of growing down over the plot as series are added.
  legend: {
    type: 'scroll',
    top: 8,
    left: 'center',
    padding: [0, 32],
  },
  grid: {
    containLabel: true,
    left: 32,
    top: 44,
    right: 32,
    bottom: 28,
  },
})
</script>

<script lang="ts" setup>
import { useElementVisibility, useResizeObserver } from '@vueuse/core'
import { init } from 'echarts'
import type { ECharts } from 'echarts'
import { merge } from 'lodash-es'
import { watch, watchEffect } from 'vue'

import { chartPalette, chartTheme } from '@/chart'
import type { Option } from '@/chart'
import { usePreferences } from '@/preferences'

const {
  option,
  loading = false,
  height = undefined,
  brushZoom = false,
} = defineProps<{
  option?: Option
  loading?: boolean
  height?: number | string | null
  /** Turns a drag across the plot into a zoom the host applies, reported through `zoom` while
  the chart's own view stays whole. */
  brushZoom?: boolean
}>()

const emit = defineEmits<{
  /** A drag selected this span of the X axis, in its own units. */
  zoom: [start: number, end: number]
}>()

const preferences = usePreferences()

let container = $shallowRef<HTMLElement | null>(null)
let instance = $shallowRef<ECharts | null>(null)
let element = $shallowRef<HTMLDivElement | null>(null)

const isVisible = $(useElementVisibility(() => container))

/** The select-zoom feature a drag runs through. ECharts sets the feature up only in a toolbox it
shows, so the toolbox shows with no buttons to see, the drag itself being the control. */
const brushOption: Option = {
  toolbox: {
    show: true,
    itemSize: 0,
    showTitle: false,
    feature: { dataZoom: { yAxisIndex: 'none', icon: { zoom: 'path://', back: 'path://' } } },
  },
}

const merged: Option | undefined = $computed(() => {
  if (option != null) {
    return merge({}, defaultOptions, brushZoom ? brushOption : {}, option)
  }

  return undefined
})

/** Whether the instance holds the select-zoom cursor, which it drops when recreated. */
let isBrushing = false

// Resetting the chart's own zoom raises a zoom event of its own, which is not a drag.
let isResetting = false

function takeBrush(target: ECharts) {
  if (!brushZoom || isBrushing) {
    return
  }

  target.dispatchAction({
    type: 'takeGlobalCursor',
    key: 'dataZoomSelect',
    dataZoomSelectActive: true,
  })
  isBrushing = true
}

function onDataZoom(
  target: ECharts,
  event: { batch?: { startValue?: unknown; endValue?: unknown }[] },
) {
  if (isResetting) {
    return
  }

  const [selected] = event.batch ?? []
  const start = Number(selected?.startValue)
  const end = Number(selected?.endValue)

  // The host shows the span by changing the axis, so the chart's own zoom goes back to whole.
  isResetting = true
  target.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
  isResetting = false

  if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
    emit('zoom', start, end)
  }
}

// The theme reads the resolved token palette, so a color mode flip rebuilds the instance
// after the DOM classes settle.
watchEffect(
  (cleanup) => {
    let created: ECharts | null = null
    if (element != null) {
      void preferences.isDarkModeEnabled
      const target = init(element, chartTheme(chartPalette()))
      target.on('datazoom', (event) => onDataZoom(target, event as never))
      created = target
      isBrushing = false
      instance = created
    }

    cleanup(() => {
      created?.dispose()
    })
  },
  { flush: 'post' },
)

watch(
  [() => merged, () => instance],
  () => {
    requestAnimationFrame(() => {
      if (merged != null && instance != null) {
        instance.setOption(merged)
        takeBrush(instance)
      }
    })
  },
  { immediate: true },
)

defineExpose({
  getDom() {
    return instance?.getDom()
  },
  on(eventType: Parameters<ECharts['on']>[0], handler: Parameters<ECharts['on']>[2]) {
    instance?.on(eventType, handler)
  },
  off(...args: Parameters<ECharts['off']>) {
    instance?.off(...args)
  },
  getOption() {
    return (instance?.getOption() ?? null) as Option | null
  },
  setOption(
    option: Option,
    params?: {
      notMerge?: boolean
      lazyUpdate?: boolean
      withDefaults?: boolean
      silent?: boolean
      replaceMerge?: string | string[]
    },
  ) {
    if (params?.withDefaults) {
      option = merge({}, defaultOptions, brushZoom ? brushOption : {}, option)
    }

    if (instance != null) {
      instance.setOption(option, params as any)
      if (params?.withDefaults) {
        takeBrush(instance)
      }
    }
  },
  resize(...args: Parameters<ECharts['resize']>) {
    return instance?.resize(...args)
  },
})

useResizeObserver(
  () => container,
  () => {
    instance?.resize()
  },
)

const containerStyle = $computed(() => {
  let computedHeight: string | undefined = undefined
  if (height != null) {
    if (typeof height === 'number') {
      computedHeight = `${height}px`
    } else {
      computedHeight = height
    }
  }

  return {
    height: computedHeight,
  }
})
</script>

<template>
  <div
    ref="container"
    class="relative max-w-full min-w-full overflow-hidden transition-opacity duration-250"
    :class="loading ? 'opacity-50' : 'opacity-100'"
    :style="containerStyle"
  >
    <div
      ref="element"
      class="absolute h-full w-full"
      :style="isVisible ? undefined : { visibility: 'hidden' }"
    />
  </div>
</template>
