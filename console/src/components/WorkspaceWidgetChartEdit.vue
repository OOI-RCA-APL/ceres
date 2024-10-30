<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { ChartWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()

const seriesSchema = $computed<any>(() => ({
  type: 'array',
  title: 'Series',
  items: {
    type: 'object',
    properties: {
      name: { type: 'string', title: 'Name', default: 'Series' },
      type: { type: 'string', title: 'Type', enum: ['line'], default: 'line' },
      particleAddress: {
        type: 'string',
        title: 'Particle Address',
        enum: engine.components.all.flatMap((current) => [current.address, current.address.all()]),
        nullable: true,
        default: null,
      },
      particleType: { type: 'string', title: 'Particle Type', nullable: true, default: null },
      particleField: { type: 'string', title: 'Particle Field', nullable: true, default: null },
    },
    required: ['name', 'type'],
  },
}))
</script>

<template>
  <div>
    <div class="column q-gutter-xs q-pa-sm">
      <schema-form-base
        v-model="widget.unit"
        :schema="{ type: 'string', title: 'Unit (Y Axis)', optional: true }"
      />
      <schema-form-base
        v-model="widget.duration"
        :schema="{ type: 'string', format: 'duration', title: 'Duration', optional: true }"
      />
    </div>
    <div class="q-pt-sm q-px-sm">
      <common-text variant="th">Series</common-text>
    </div>
    <schema-form-base v-model="widget.series" :schema="seriesSchema" />
  </div>
</template>
