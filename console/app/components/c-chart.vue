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
} = defineProps<{
  option?: Option
  loading?: boolean
  height?: number | string | null
}>()

const preferences = usePreferences()

let container = $shallowRef<HTMLElement | null>(null)
let instance = $shallowRef<ECharts | null>(null)
let element = $shallowRef<HTMLDivElement | null>(null)

const isVisible = $(useElementVisibility(() => container))

const merged: Option | undefined = $computed(() => {
  if (option != null) {
    return merge({}, defaultOptions, option)
  }

  return undefined
})

// The theme reads the resolved token palette, so a color mode flip rebuilds the instance
// after the DOM classes settle.
watchEffect(
  (cleanup) => {
    let created: ECharts | null = null
    if (element != null) {
      void preferences.isDarkModeEnabled
      created = init(element, chartTheme(chartPalette()))
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
      if (merged != null) {
        instance?.setOption(merged)
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
      option = merge({}, defaultOptions, option)
    }

    instance?.setOption(option, params as any)
  },
  appendData(params: Parameters<ECharts['appendData']>[0]) {
    if (instance == null) {
      return
    }

    instance.appendData(params)
    // Appending marks the chart dirty without drawing it, and the draw is left to the next
    // animation frame, so records sit in the series store unpainted until one comes. Driving a
    // frame here paints them, which nothing else in a chart that is only receiving data does.
    instance.resize()
    instance.getZr().animation.update()
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
    :class="[$style.container, loading && $style.loading]"
    :style="containerStyle"
  >
    <div
      ref="element"
      :class="$style.instance"
      :style="isVisible ? undefined : { visibility: 'hidden' }"
    />
  </div>
</template>

<style module>
.container {
  position: relative;
  min-width: 100%;
  max-width: 100%;
  transition: opacity 0.25s;
  overflow: hidden;
  opacity: 1;
}

.instance {
  position: absolute;
  width: 100%;
  height: 100%;
}

.loading {
  opacity: 0.5;
}
</style>
