<template>
  <chart :options="options" />
</template>

<script lang="ts" setup>
import type { ElementInfo } from '@/element'
import Chart, { Option } from '@/chart'

defineProps<{
  element: ElementInfo
}>()

const options = $computed(
  () =>
    ({
      type: 'horizontal column',
      backgroundColor: 'red',
      series: [
        {
          points: [
            { x: 'A', y: 50 },
            { x: 'B', y: 30 },
            { x: 'C', y: 50 },
          ],
          backgroundStyle: {
            color: 'rgba(220, 220, 220, 0.8)',
          },
        },
      ],
    } as Option)
)
</script>
