<script lang="ts" setup>
import { ChartElement } from '@/api/elements'
import Chart from '@/components/Chart.vue'

const { element } = defineProps<{
  element: ChartElement
}>()
</script>

<template>
  <chart :height="element.height" :option="element.value" />
</template>
