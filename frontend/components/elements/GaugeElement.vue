<template>
  <chart :options="options" />
</template>

<script lang="ts" setup>
import type { ElementInfo } from '../../mock'
import Chart, { Options } from '../Chart.vue'

defineProps<{
  element: ElementInfo
}>()

const options: Options = {
  type: 'horizontal column',
  series: [
    {
      points: [
        { x: 'A', y: 50 },
        { x: 'B', y: 30 },
        { x: 'C', y: 50 },
      ],
    },
  ],
}
</script>
