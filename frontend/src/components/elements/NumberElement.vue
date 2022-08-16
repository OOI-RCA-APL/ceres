<template>
  <chart autoresize class="self-chart" :option="options" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import { createColorStops, NumberElementInfo } from '@/element'
import { useQuasar } from 'quasar'

const { info } = defineProps<{
  info: NumberElementInfo
}>()

const quasar = useQuasar()

const valueText = $computed(() => `${info.value}${info.unit}`)
const color = $computed(() => createColorStops(info.value, info.color, quasar.dark.isActive))

const options = $computed(
  () =>
    ({
      backgroundColor: 'transparent',
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
            fontSize: 22,
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
  height: 48px;
  max-width: 180px;
}
</style>
