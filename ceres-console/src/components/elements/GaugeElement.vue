<template>
  <chart autoresize class="self-chart" :option="options" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import { createColorStops, GuageElementInfo } from '@/element'
import { useQuasar } from 'quasar'

const { info } = defineProps<{
  info: GuageElementInfo
}>()

const quasar = useQuasar()

const valueText = $computed(() => `${info.value}${info.unit}`)
const valueTextScaling = $computed(() => {
  const maxUnscaledCharacters = 4
  return 1 - 0.1 * Math.max(valueText.length - maxUnscaledCharacters, 0)
})

const color = $computed(() => createColorStops(info.value, info.color, quasar.dark.isActive))

const min = Math.min(info.range.min)
const max = Math.max(info.range.max)

const options = $computed(
  () =>
    ({
      backgroundColor: 'transparent',
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
            length: -6,
            splitNumber: 4,
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
            showMinLabel: true,
            showMaxLabel: true,
            fontSize: 10,
            distance: -18,
            padding: [3, -3],
            overflow: 'truncate',
          },
          detail: {
            valueAnimation: false,
            fontSize: 22 * valueTextScaling,
            fontWeight: 300,
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

<style lang="scss" scoped>
.self-chart {
  max-width: 180px;
  min-height: 170px;
  padding-top: 12px;
}
</style>
