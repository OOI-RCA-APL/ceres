<script lang="ts" setup>
import { useDerivedChartUnit } from '@/particle-types'
import { ChartWidgetFitModel, useWorkspace } from '@/workspace'
import type { ChartWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const workspace = useWorkspace()

// Offered as the unit input's placeholder so a blank setting says what the chart will show.
const derivedUnit = $(useDerivedChartUnit(() => widget, workspace).unit)
</script>

<template>
  <c-workspace-widget-settings :widget>
    <c-text class="mb-2" variant="title2">Particles</c-text>
    <!-- The selector's own "Manual Entry" section carries the margin under it. -->
    <c-particle-series-selector v-model="widget.particles" collapse-unselected show-selected />
    <c-text class="mb-2" variant="title2">Display</c-text>
    <div class="flex flex-col gap-1">
      <div class="grid grid-cols-2 gap-x-2">
        <c-schema-form-value
          v-model="widget.display"
          :schema="{
            type: 'string',
            title: 'Display',
            enum: ['line', 'scatter', 'bar'],
          }"
        />
        <c-schema-form-value
          v-model="widget.unit"
          :schema="{
            type: 'string',
            title: 'Unit (Y Axis)',
            optional: true,
            default: derivedUnit || undefined,
          }"
        />
      </div>
      <div class="grid grid-cols-2 gap-x-2">
        <c-schema-form-value
          v-model="widget.after"
          :schema="{ type: 'string', format: 'date-time', title: 'After', optional: true }"
        />
        <c-schema-form-value
          v-model="widget.timespan"
          :schema="{
            type: 'string',
            format: 'duration',
            title: 'Timespan',
            optional: true,
            default: '1h',
          }"
        />
      </div>
      <!-- A row gap as well, this being the one block that wraps onto a second row. -->
      <div class="grid grid-cols-2 gap-x-2 gap-y-1">
        <c-schema-form-value
          v-model="widget.fit"
          :schema="{
            type: 'string',
            title: 'Fit To (Y Axis)',
            enum: ChartWidgetFitModel.options,
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
        <c-schema-form-value
          v-model="widget.fromZero"
          :schema="{
            type: 'boolean',
            title: 'From Zero',
          }"
        />
        <c-schema-form-value
          v-model="widget.flipY"
          :schema="{
            type: 'boolean',
            title: 'Flip Y Axis',
          }"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
