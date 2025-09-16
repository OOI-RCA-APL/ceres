<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { ChartWidgetParticle, ChartWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const engine = useEngine()

const particlesSchema = $computed<any>(() => ({
  type: 'array',
  title: 'Particles',
  items: {
    type: 'object',
    properties: {
      address: {
        type: 'string',
        title: 'Particle Address',
        enum: engine.components.all.flatMap((current) => [
          current.address.toString(),
          current.address.all().toString(),
        ]),
      },
      type: { type: 'string', title: 'Particle Type' },
      series: {
        type: 'array',
        title: 'Series',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string', title: 'Name', default: 'Series' },
            field: { type: 'string', title: 'Particle Field' },
          },
          required: ['name'],
        },
      },
    },
    required: ['series'],
  },
}))
</script>

<template>
  <div>
    <div class="column q-gutter-xs q-pa-sm">
      <schema-form-base
        v-model="widget.display"
        :schema="{
          type: 'string',
          title: 'Display',
          enum: ['line', 'scatter', 'bar'],
        }"
      />
      <schema-form-base
        v-model="widget.unit"
        :schema="{ type: 'string', title: 'Unit (Y Axis)', optional: true }"
      />
      <schema-form-base
        v-model="widget.after"
        :schema="{ type: 'string', format: 'date-time', title: 'After', optional: true }"
      />
      <schema-form-base
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
    <div class="q-pt-sm q-px-sm">
      <common-text variant="th">Particles</common-text>
    </div>
    <schema-form-base
      :model-value="
        widget.particles.map((current) => ({
          ...current,
          address: current.address?.toString(),
        }))
      "
      :schema="particlesSchema"
      @update:model-value="
        (particles: any) => {
          const updated = particles.map((current: ChartWidgetParticle) => ({
            ...current,
            address: current.address ? new AddressSelector(current.address) : current.address,
          }))

          if (JSON.stringify(updated) !== JSON.stringify(widget.particles)) {
            widget.particles = updated
          }
        }
      "
    />
  </div>
</template>
