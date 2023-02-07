<template>
  <chart autoresize class="self-chart" :option="options" />
</template>

<script lang="ts" setup>
import { Option } from '@/chart'
import Chart from '@/components/Chart.vue'
import { GaugeDisplayInfo } from '@/display'
import { useQuasar } from 'quasar'

const { info } = defineProps<{
  info: GaugeDisplayInfo
}>()

const quasar = useQuasar()

const segments = $computed(() => {
  function createSegment(color: string, size: number) {
    return {
      type: 'bar',
      silent: true,
      animation: false,
      barWidth: 18,
      itemStyle: {
        normal: {
          opacity: 0.7,
          borderColor: quasar.dark.isActive ? 'white' : 'black',
          borderRadius: 1,
          color,
        },
      },
      stack: 'total',
      data: [size],
    }
  }
  if (info.color == null) {
    return [createSegment('transparent', info.range.max)]
  }

  if (typeof info.color === 'string') {
    return [createSegment(info.color, info.range.max)]
  }

  const stops = info.color

  return stops.map((stop, i) => {
    const previous = stops[i - 1] ?? null
    return createSegment(stop.color, stop.value - (previous?.value ?? 0))
  })
})

const options = $computed(
  () =>
    ({
      backgroundColor: 'transparent',
      grid: {
        top: '30%',
        left: '10%',
        right: '10%',
        bottom: '20%',
        containLabel: true,
      },
      yAxis: {
        show: true,
        boundaryGap: false,
        data: [info.unit],
        axisLabel: {
          color: quasar.dark.isActive ? 'white' : 'black',
        },
      },
      xAxis: {
        type: 'value',
        min: info.range.min,
        max: info.range.max,
        axisLabel: {
          fontFamily: 'Roboto',
          opacity: 1,
          color: quasar.dark.isActive ? 'white' : 'black',
        },
      },
      series: [
        {
          type: 'scatter',
          symbol: 'triangle',
          silent: true,
          itemStyle: {
            normal: {
              color: 'white',
              borderColor: 'black',
              borderWidth: 1,
              borderRadius: 1,
            },
          },
          symbolSize: [10, 10],
          symbolOffset: ['0%', '41%'],
          data: [info.value],
          label: {
            fontFamily: 'Roboto',
            opacity: 1,
            show: true,
            offset: [0, -25],
            color: quasar.dark.isActive ? 'white' : 'black',
            formatter: `{c}${info.unit ?? ''}`,
          },
        },
        ...segments,
      ],
    } as Option)
)
</script>

<style lang="scss" scoped>
.self-chart {
  margin-top: 8px;
  min-height: 70px;
}
</style>
