<template>
  <chart class="self-chart-root" :option="info.value" :style="{ height: `${info.height}px` }" />
</template>

<script lang="ts" setup>
import Chart from '@/components/Chart.vue'
import { ChartDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: ChartDisplayInfo
}>()
</script>

<style lang="scss" scoped>
.self-chart-root {
  padding-top: 8px;
}
</style>
