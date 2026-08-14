<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import ParticleSeriesSelector from '@/components/ParticleSeriesSelector.vue'
import WorkspaceWidgetSettings from '@/components/WorkspaceWidgetSettings.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { useDerivedChartUnit } from '@/particle-types'
import { ChartWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const workspace = useWorkspace()

// Offered as the unit input's placeholder so a blank setting says what the chart will show.
const derivedUnit = $(useDerivedChartUnit(() => widget, workspace).unit)
</script>

<template>
  <workspace-widget-settings :widget>
    <div class="q-pb-xs">
      <common-text variant="th">Particle Fields</common-text>
    </div>
    <!-- The selector's own "Manual Entry" section carries the margin under it. -->
    <particle-series-selector v-model="widget.particles" collapse-unselected show-selected />
    <div class="column q-gutter-xs">
      <div class="q-col-gutter-x-sm row">
        <div class="col-6">
          <schema-form-value
            v-model="widget.display"
            :schema="{
              type: 'string',
              title: 'Display',
              enum: ['line', 'scatter', 'bar'],
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
            v-model="widget.unit"
            :schema="{
              type: 'string',
              title: 'Unit (Y Axis)',
              optional: true,
              default: derivedUnit || undefined,
            }"
          />
        </div>
      </div>
      <div class="q-col-gutter-x-sm row">
        <div class="col-6">
          <schema-form-value
            v-model="widget.after"
            :schema="{ type: 'string', format: 'date-time', title: 'After', optional: true }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
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
      </div>
    </div>
  </workspace-widget-settings>
</template>
