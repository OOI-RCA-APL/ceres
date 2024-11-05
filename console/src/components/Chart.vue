<script lang="ts">
const defaultOptions: Option = {
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
    axisLabel: {
      hideOverlap: true,
    },
  },
  useUTC: true,
  grid: {
    containLabel: true,
    left: 32,
    top: 44,
    right: 32,
    bottom: 28,
  },
}
</script>

<script lang="ts" setup>
import { ECharts } from 'echarts'
import { merge } from 'lodash'
import { watchEffect } from 'vue'
import EChart from 'vue-echarts'

import { Option } from '@/chart'

const {
  loading = false,
  height = undefined,
  option,
} = $defineProps<{
  loading?: boolean
  height?: number | string | null
  option: Option
}>()

const container = $shallowRef<HTMLElement | null>(null)
const instance = $shallowRef<ECharts | null>(null)

const merged: Option = $computed(() => merge(option, defaultOptions))
// Use `setOption` on the EChart instance to avoid the chart being completely recreated.
watchEffect(() => {
  instance?.setOption(merged)
})

// Make resizing smoother.
const autoresize = $computed(() => ({
  throttle: 25,
}))

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
    <e-chart key="chart" ref="instance" :autoresize :class="$style.instance" />
  </div>
</template>

<style lang="scss" module>
.container {
  position: relative;
  min-width: 100%;
  max-width: 100%;
  transition: opacity 0.25s;
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
