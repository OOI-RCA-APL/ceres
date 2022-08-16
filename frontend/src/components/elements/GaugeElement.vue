<template>
  <chart autoresize :option="options" style="min-height: 160px; padding-top: 12px" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import { createColorStops, GuageElementInfo } from '@/element'

const { info } = defineProps<{
  info: GuageElementInfo
}>()

const valueText = $computed(() => `${info.value}${info.unit}`)
const valueTextScaling = $computed(() => {
  const maxUnscaledCharacters = 4
  return 1 - 0.1 * Math.max(valueText.length - maxUnscaledCharacters, 0)
})

const color = $computed(() => createColorStops(info.value, info.color))

const min = Math.min(info.range.min)
const max = Math.max(info.range.max)

const options = $computed(
  () =>
    ({
      series: [
        {
          min: min,
          max: max,
          animation: false,
          type: 'gauge',
          axisLine: {
            lineStyle: {
              width: 2,
              color,
            },
          },
          pointer: {
            showAbove: false,
            icon: 'triangle',
            length: '15%',
            offsetCenter: [0, '-75%'],
            itemStyle: {
              color: 'auto',
            },
          },
          axisTick: {
            distance: 0,
            length: 4,
            lineStyle: {
              color: 'auto',
              width: 1,
            },
          },
          splitLine: {
            distance: 0,
            length: -5,
            lineStyle: {
              color: '#fff',
              width: 0,
            },
          },
          axisLabel: {
            color: 'auto',
            hideOverlap: true,
            fontSize: 10,
            distance: -16,
            padding: [2, -8],
            overflow: 'truncate',
          },
          detail: {
            valueAnimation: false,
            fontSize: 26 * valueTextScaling,
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
