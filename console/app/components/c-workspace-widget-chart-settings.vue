<script lang="ts" setup>
import { useDerivedChartUnit } from '@/particle-types'
import { useWorkspace } from '@/workspace'
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
    <div class="pb-1">
      <c-text variant="th">Particle Fields</c-text>
    </div>
    <!-- The selector's own "Manual Entry" section carries the margin under it. -->
    <c-particle-series-selector v-model="widget.particles" collapse-unselected show-selected />
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
      <div class="grid grid-cols-2 gap-x-2">
        <c-schema-form-value
          v-model="widget.fit"
          :schema="{
            type: 'string',
            title: 'Fit (Y Axis)',
            description: 'From zero anchors the axis at zero, data hugs the plotted extent.',
            enum: ['from-zero', 'data'],
          }"
        />
        <c-schema-form-value
          v-model="widget.flipY"
          :schema="{
            type: 'boolean',
            title: 'Flip Y Axis',
            description: 'Draw the axis positive-down, for depth-like series.',
          }"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
