<script setup lang="ts">
import { Option } from '@/chart'
import { ECharts } from 'echarts'
import EChart from 'vue-echarts'

const {
  loading = false,
  height = undefined,
  option,
} = defineProps<{
  loading?: boolean
  height?: number
  option: Option
}>()

const container = $ref<HTMLElement | null>(null)
const instance = $ref<ECharts | null>(null)

const appliedOptions: Option = $computed(() => ({
  ...option,
  backgroundColor: 'transparent',
  useUTC: true,
}))

const containerStyle = $computed(() => ({
  height: height != null ? `${height}px` : undefined,
}))
</script>

<template>
  <div ref="container" :class="$style.container" :style="containerStyle">
    <e-chart
      ref="instance"
      :autoresize="{ throttle: 350 }"
      :class="$style.instance"
      :loading="loading"
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
