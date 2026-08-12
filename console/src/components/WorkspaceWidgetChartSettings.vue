<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import ParticleSeriesSelector from '@/components/ParticleSeriesSelector.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ChartWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()
</script>

<template>
  <div>
    <div class="column q-gutter-xs q-pa-sm">
      <schema-form-value
        v-model="widget.display"
        :schema="{
          type: 'string',
          title: 'Display',
          enum: ['line', 'scatter', 'bar'],
        }"
      />
      <schema-form-value
        v-model="widget.unit"
        :schema="{ type: 'string', title: 'Unit (Y Axis)', optional: true }"
      />
      <schema-form-value
        v-model="widget.after"
        :schema="{ type: 'string', format: 'date-time', title: 'After', optional: true }"
      />
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
    <div class="q-px-sm">
      <div class="q-pb-xs">
        <common-text variant="th">Particle Fields</common-text>
      </div>
      <particle-series-selector v-model="widget.particles" show-selected />
    </div>
  </div>
</template>
