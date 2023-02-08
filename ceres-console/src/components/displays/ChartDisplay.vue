<template>
  <chart :option="info.value" :style="{ height: `${info.height}px` }" />
</template>

<script lang="ts" setup>
import Chart from '@/components/Chart.vue'
import { ChartDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: ChartDisplayInfo
}>()
</script>
