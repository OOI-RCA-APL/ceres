<template>
  <chart autoresize :option="options" style="height: 48px" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import { createColorStops, NumberElementInfo } from '@/element'

const { info } = defineProps<{
  info: NumberElementInfo
}>()

const valueText = $computed(() => `${info.value}${info.unit}`)
const color = $computed(() => createColorStops(info.value, info.color))

const options = $computed(
  () =>
    ({
      series: [
        {
          type: 'gauge',
          axisLine: {
            show: false,
            lineStyle: {
              width: 1,
              color,
            },
          },
          pointer: {
            show: false,
          },
          axisTick: {
            show: false,
          },
          splitLine: {
            show: false,
          },
          axisLabel: {
            show: false,
          },
          detail: {
            valueAnimation: false,
            fontSize: 26,
            formatter: valueText,
            color: 'auto',
            offsetCenter: [0, '0%'],
          },
          data: [
            {
              value: info.value,
            },
          ],
        },
      ],
    } as Option)
)
</script>
