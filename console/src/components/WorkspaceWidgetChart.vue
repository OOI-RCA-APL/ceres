<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'

import { useEngine } from '@/api/engine'
import { Option, DataValue } from '@/chart'
import Chart from '@/components/Chart.vue'
import { debouncedComputed } from '@/utilities'
import { ChartWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()

type Results = Record<string, DataValue[][]>

async function getSeriesResults() {
  const mapping = {} as Results

  await Promise.all(
    widget.particles.flatMap(async ({ address, type, series }) => {
      const particles = await engine.particles.getAll({
        address,
        type,
        after: widget.after,
        before: widget.before,
        timespan: widget.timespan,
        limit: 5000,
      })

      series.map((series) => {
        mapping[series.name] = particles.flatMap((particle) => {
          if (series.field == null) {
            return []
          }

          const timestamp = particle.timestamp
          let value = particle.data[series.field]
          if (typeof value !== 'number' && typeof value !== 'string') {
            if (typeof value === 'boolean') {
              return [[timestamp, value as any as number]]
            }

            return []
          }

          return [[timestamp, value]]
        })
      })
    })
  )

  return mapping
}

const query = useQuery({
  queryFn: getSeriesResults,
  queryKey: debouncedComputed(() => [JSON.stringify(widget.particles)], 1000),
  refetchInterval: 5000,
  initialData: () => ({}),
})

const results: Results = $computed(() => query.data.value ?? {})

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
  series: widget.particles.flatMap((particle) =>
    particle.series.map((series) => ({
      name: series.name,
      data: results[series.name],
      type: widget.display,
      showSymbol: false,
      symbolSize: 6,
    }))
  ),
}))
</script>

<template>
  <chart height="100px" :option="option" />
</template>
