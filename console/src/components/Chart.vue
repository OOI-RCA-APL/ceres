<script lang="ts">
const defaultOptions: Option = {
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
    nameLocation: 'end',
    nameGap: 0,
    splitArea: {
      show: true,
    },
    nameTextStyle: {
      align: 'right',
      verticalAlign: 'top',
      padding: [24, 0, 0, 0],
    },
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
    bottom: 24,
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
watchEffect(() => {
  instance?.setOption(merged)
})

const autoresize = $computed(() => ({
  throttle: 250,
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
  <div ref="container" :class="$style.container" :style="containerStyle">
    <e-chart key="chart" ref="instance" :autoresize :class="$style.instance" :loading />
  </div>
</template>

<style lang="scss" module>
.container {
  position: relative;
  min-width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.instance {
  position: absolute;
  width: 100%;
  height: 100%;
}
</style>
