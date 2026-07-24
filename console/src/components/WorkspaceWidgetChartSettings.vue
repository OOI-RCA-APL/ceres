<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import CommonText from '@/components/CommonText.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import { ChartWidgetParticleModel, ChartWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const seriesSchema = {
  type: 'array',
  title: 'Series',
  items: {
    type: 'object',
    properties: {
      field: { type: 'string', title: 'Field' },
      name: { type: 'string', title: 'Label' },
    },
  },
} as const

function addParticle() {
  widget.particles = [...widget.particles, ChartWidgetParticleModel.parse({})]
}

function removeParticle(index: number) {
  widget.particles = widget.particles.filter((_, current) => current !== index)
}
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
    <div class="q-pt-sm q-px-sm">
      <common-text variant="th">Particles</common-text>
    </div>
    <div class="column q-gutter-sm q-pa-sm">
      <q-card v-for="(particle, index) in widget.particles" :key="index" bordered flat>
        <div class="column q-gutter-xs q-pa-sm">
          <div class="items-center row">
            <div class="col-grow">
              <workspace-address-select
                :model-value="particle.address?.toString() ?? null"
                @update:model-value="
                  (value) =>
                    (particle.address =
                      value != null && value !== '' ? new AddressSelector(value) : null)
                "
              />
            </div>
            <q-btn
              dense
              flat
              :icon="icons.cancel"
              round
              size="9px"
              @click="removeParticle(index)"
            />
          </div>
          <schema-form-value
            v-model="particle.type"
            :schema="{ type: 'string', title: 'Particle Type', optional: true }"
          />
          <schema-form-value v-model="particle.series" :schema="seriesSchema" />
        </div>
      </q-card>
      <div class="text-center">
        <schema-form-node-add-button @click="addParticle" />
      </div>
    </div>
  </div>
</template>
