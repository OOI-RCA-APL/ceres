<script lang="ts" setup>
import type { ParticleManualEntry } from '@/components/c-particle-manual-entry.vue'
import { addParticleSeries } from '@/particle-series'
import { useDerivedChartUnit } from '@/particle-types'
import { storedFields, storedRange, type TimeRange } from '@/time-range'
import { ChartWidgetFitModel, ChartWidgetSeriesModel, useWorkspace } from '@/workspace'
import type { ChartWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const workspace = useWorkspace()

// Offered as the unit input's placeholder so a blank setting says what the chart will show.
const derivedUnit = $(useDerivedChartUnit(() => widget, workspace).unit)

const storedDefault = $computed<TimeRange>({
  get: () => storedRange(widget.after, widget.timespan),
  set: (range) => {
    const { after, timespan } = storedFields(range)
    widget.after = after
    widget.timespan = timespan
  },
})

function addEntry(entry: ParticleManualEntry) {
  const series = ChartWidgetSeriesModel.parse({ field: entry.field, label: entry.label })
  widget.particles = addParticleSeries(
    widget.particles,
    entry.address,
    entry.type,
    series,
    entry.connection,
  )
}
</script>

<template>
  <c-workspace-widget-settings :widget>
    <!-- The chart itself, so every change below shows as it is made. -->
    <div class="border-default mb-4 h-48 overflow-hidden rounded-md border p-2">
      <c-workspace-widget-chart preview :widget="widget" />
    </div>
    <c-text class="mb-2" variant="title2">Data</c-text>
    <c-particle-data-picker
      v-model="widget.particles"
      class="mb-2"
      collapse-unselected
      :focus-search="widget.particles.length === 0"
    />
    <c-particle-manual-entry class="mb-2" labeled @choose="addEntry" />
    <c-chart-series-list v-model="widget.particles" class="mb-4" />
    <c-text class="mb-2" variant="title2">Range</c-text>
    <!-- The range the chart opens with, which each viewer then moves on the chart itself. -->
    <c-time-range v-model="storedDefault" class="mb-4" />
    <c-text class="mb-2" variant="title2">Display</c-text>
    <div class="flex flex-col gap-1">
      <div class="grid grid-cols-2 gap-x-2">
        <c-schema-form-value
          v-model="widget.unit"
          :schema="{
            type: 'string',
            title: 'Unit (Y Axis)',
            optional: true,
            default: derivedUnit || undefined,
          }"
        />
        <c-schema-form-value
          v-model="widget.decimals"
          :schema="{
            type: 'integer',
            title: 'Decimals',
            minimum: 0,
            maximum: 10,
            default: 2,
          }"
        />
      </div>
      <div class="grid grid-cols-4 gap-x-2">
        <c-schema-form-value
          v-model="widget.fit"
          class="col-span-2"
          :schema="{
            type: 'string',
            title: 'Fit To (Y Axis)',
            enum: ChartWidgetFitModel.options,
          }"
        />
        <c-schema-form-value
          v-model="widget.fromZero"
          align="center"
          :schema="{
            type: 'boolean',
            title: 'From Zero',
          }"
          :show-type="false"
        />
        <c-schema-form-value
          v-model="widget.flipY"
          align="center"
          :schema="{
            type: 'boolean',
            title: 'Flip Y Axis',
          }"
          :show-type="false"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
