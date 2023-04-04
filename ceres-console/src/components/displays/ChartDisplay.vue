<script lang="ts" setup>
import Chart from '@/components/Chart.vue'
import { ChartDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: ChartDisplayInfo
}>()
</script>

<template>
  <chart :class="$style.root" :option="info.value" :style="{ height: `${info.height}px` }" />
</template>

<style module>
.root {
  padding-top: 8px;
}
</style>
