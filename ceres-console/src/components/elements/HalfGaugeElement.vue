<template>
  <chart autoresize class="self-chart" :option="options" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import { ColorStop, createColorStops, GuageElementInfo } from '@/element'
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

const bgColor = $computed(() => createColorStops(info.value, info.color, quasar.dark.isActive))
const color = $computed(() =>
  typeof info.color !== 'string'
    ? info.color?.find((color: ColorStop) => info.value <= color.value)?.color
    : info.color
)
console.log(color)

const min = Math.min(info.range.min)
const max = Math.max(info.range.max)

const options = $computed(
  () =>
    ({
      backgroundColor: 'transparent',
      series: [
        {
          type: 'gauge',
          center: ['50%', '40%'],
          startAngle: 180,
          endAngle: 0,
          min: min,
          max: max,
          splitNumber: 10,
          itemStyle: {
            color: color,
          },
          progress: {
            show: true,
            width: 10,
          },
          pointer: {
            icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
            length: '12%',
            width: 8,
            offsetCenter: [0, '-65%'],
            itemStyle: {
              color: 'auto',
            },
          },
          axisLine: {
            lineStyle: {
              width: 10,
              color: bgColor,
              opacity: 0.25,
            },
          },
          axisTick: {
            show: false,
            distance: -20,
            splitNumber: 5,
            lineStyle: {
              width: 2,
              color: '#999',
            },
          },
          splitLine: {
            show: false,
            distance: -25,
            length: 10,
            lineStyle: {
              width: 3,
              color: '#999',
            },
          },
          axisLabel: {
            distance: -22,
            color: '#999',
            fontSize: 14,
            show: false,
          },
          anchor: {
            show: false,
          },
          title: {
            show: false,
          },
          detail: {
            valueAnimation: true,
            offsetCenter: [0, '-20%'],
            fontSize: 22 * valueTextScaling,
            fontWeight: 'bolder',
            formatter: valueText,
            color: 'auto',
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
  max-width: 200px;
  min-height: 170px;
  padding-top: 4px;
}
</style>
