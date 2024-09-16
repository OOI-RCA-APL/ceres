<script setup lang="ts">
import { ECharts } from 'echarts'
import EChart from 'vue-echarts'

import { Option } from '@/chart'

const {
  loading = false,
  height = undefined,
  option,
} = defineProps<{
  loading?: boolean
  height?: number | string | null
  option: Option
}>()

const container = $ref<HTMLElement | null>(null)
const instance = $ref<ECharts | null>(null)

const appliedOptions: Option = $computed(() => ({
  ...option,
  backgroundColor: 'transparent',
  useUTC: true,
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
    <e-chart
      ref="instance"
      :autoresize="{ throttle: 350 }"
      :class="$style.instance"
      :loading
      :option="appliedOptions"
    />
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
