<script lang="ts" setup>
import { GaugeElement } from '@/api/elements'
import { Option } from '@/chart'
import Chart from '@/components/Chart.vue'
import { usePreferences } from '@/preferences'

const { element } = defineProps<{
  element: GaugeElement
}>()

const preferences = usePreferences()

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
          borderColor: preferences.isDarkModeEnabled ? 'white' : 'black',
          borderRadius: 1,
          color,
        },
      },
      stack: 'total',
      data: [size],
    }
  }
  if (element.color == null) {
    return [createSegment('transparent', element.max)]
  }

  if (typeof element.color === 'string') {
    return [createSegment(element.color, element.max)]
  }

  const stops = element.color

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
        data: [element.unit],
        axisLabel: {
          color: preferences.isDarkModeEnabled ? 'white' : 'black',
        },
      },
      xAxis: {
        type: 'value',
        min: element.min,
        max: element.max,
        axisLabel: {
          fontFamily: 'Roboto',
          opacity: 1,
          color: preferences.isDarkModeEnabled ? 'white' : 'black',
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
          data: [element.value],
          label: {
            fontFamily: 'Roboto',
            opacity: 1,
            show: true,
            offset: [0, -25],
            color: preferences.isDarkModeEnabled ? 'white' : 'black',
            formatter: `{c}${element.unit ?? ''}`,
          },
        },
        ...segments,
      ],
    } as Option)
)
</script>

<template>
  <chart :class="$style.root" :height="70" :option="options" />
</template>

<style module>
.root {
  margin-top: 8px;
}
</style>
