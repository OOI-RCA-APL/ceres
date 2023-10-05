<script lang="ts" setup>
import { ChartElement } from '@/api/models'
import Chart from '@/components/Chart.vue'

const { element } = defineProps<{
  element: ChartElement
}>()
</script>

<template>
  <chart :class="$style.root" :option="element.value" :style="{ height: `${element.height}px` }" />
</template>

<style module>
.root {
  padding-top: 8px;
}
</style>
