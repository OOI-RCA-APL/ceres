<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import CommonText from '@/components/CommonText.vue'
import ParticleFieldSelect from '@/components/ParticleFieldSelect.vue'
import ParticleTypeSelect from '@/components/ParticleTypeSelect.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormNodeAddButton from '@/components/schema-form/SchemaFormNodeAddButton.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import {
  ChartWidgetParticleModel,
  ChartWidgetSeriesModel,
  ChartWidget,
  useWorkspace,
} from '@/workspace'

const { widget } = defineProps<{
  widget: ChartWidget
}>()

const workspace = useWorkspace()

function addParticle() {
  widget.particles = [...widget.particles, ChartWidgetParticleModel.parse({})]
}

function removeParticle(index: number) {
  widget.particles = widget.particles.filter((_, current) => current !== index)
}

function addSeries(particleIndex: number) {
  const particle = widget.particles[particleIndex]
  particle.series = [...particle.series, ChartWidgetSeriesModel.parse({})]
}

function removeSeries(particleIndex: number, seriesIndex: number) {
  const particle = widget.particles[particleIndex]
  particle.series = particle.series.filter((_, current) => current !== seriesIndex)
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
          <particle-type-select
            :address="workspace.resolveAddress(particle.address)?.toString() ?? null"
            :model-value="particle.type ?? null"
            @update:model-value="(value) => (particle.type = value)"
          />
          <common-text variant="th">Series</common-text>
          <div class="column q-gutter-xs">
            <div
              v-for="(series, seriesIndex) in particle.series"
              :key="series.id"
              class="items-center q-gutter-xs row"
            >
              <div class="col-grow">
                <particle-field-select
                  :address="workspace.resolveAddress(particle.address)?.toString() ?? null"
                  :model-value="series.field ?? null"
                  :particle-type="particle.type ?? null"
                  @update:model-value="(value) => (series.field = value)"
                />
              </div>
              <div class="col-grow">
                <schema-form-value
                  v-model="series.label"
                  :schema="{ type: 'string', title: 'Label', optional: true }"
                />
              </div>
              <q-btn
                dense
                flat
                :icon="icons.cancel"
                round
                size="9px"
                @click="removeSeries(index, seriesIndex)"
              />
            </div>
            <div class="text-center">
              <schema-form-node-add-button @click="addSeries(index)" />
            </div>
          </div>
        </div>
      </q-card>
      <div class="text-center">
        <schema-form-node-add-button @click="addParticle" />
      </div>
    </div>
  </div>
</template>
