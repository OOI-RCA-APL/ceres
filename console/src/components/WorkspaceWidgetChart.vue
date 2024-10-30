<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'

import { useEngine } from '@/api/engine'
import { Option } from '@/chart'
import Chart from '@/components/Chart.vue'
import { debouncedComputed } from '@/utilities'
import { ChartWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()

async function getSeriesResults() {
  const mapping = {} as Record<string, any[]>

  await Promise.all(
    widget.series.map(async (series) => {
      const particles = await engine.particles.getAll({
        address: series.particleAddress,
        type: series.particleType,
        max_age: widget.duration,
        limit: 5000,
      })

      mapping[series.name] = particles.flatMap((particle) => {
        if (series.particleField == null) {
          return []
        }

        const timestamp = particle.timestamp
        const value = particle.data[series.particleField]
        if (typeof value !== 'boolean' && typeof value !== 'number' && typeof value !== 'string') {
          return []
        }

        return [[timestamp, value]]
      })
    })
  )

  return mapping
}

const query = useQuery({
  queryFn: getSeriesResults,
  queryKey: debouncedComputed(() => [JSON.stringify(widget.series)], 1000),
  refetchInterval: 5000,
  initialData: {},
})

const results = $computed(() => query.data.value ?? {})

const option: Option = $computed(() => ({
  legend: { show: true },
  tooltip: { trigger: 'axis' },
  dataZoom: [{ type: 'inside' }],
  xAxis: {
    name: 'Time',
    type: 'time',
  },
  yAxis: {
    name: widget.unit ?? '',
  },
  series: widget.series.map((series) => ({
    name: series.name,
    data: results[series.name],
    type: series.type,
    showSymbol: false,
  })),
}))
</script>

<template>
  <chart height="100px" :option="option as any" />
</template>
