<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import CommonText from '@/components/CommonText.vue'
import ParticleFieldSelect from '@/components/ParticleFieldSelect.vue'
import ParticleTypeSelect from '@/components/ParticleTypeSelect.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import WorkspaceWidgetValue from '@/components/WorkspaceWidgetValue.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ValueWidget, TextWeightModel, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: ValueWidget
}>()

const workspace = useWorkspace()

const resolvedParticleAddress = $computed(
  () => workspace.resolveAddress(widget.particleAddress)?.toString() ?? null
)
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ widget.name }}</common-text>
    <q-card bordered class="q-mb-md q-pa-sm" flat>
      <workspace-widget-value :widget="widget" />
    </q-card>
    <div>
      <common-text class="q-mb-sm" variant="title2">Particles</common-text>
      <div class="q-col-gutter-sm q-mb-sm row">
        <div class="col-6">
          <workspace-address-select
            :model-value="widget.particleAddress?.toString() ?? null"
            @update:model-value="
              (value) =>
                (widget.particleAddress =
                  value != null && value !== '' ? AddressSelector.parse(value) : null)
            "
          />
        </div>
        <div class="col-6">
          <particle-type-select
            :address="resolvedParticleAddress"
            :model-value="widget.particleType ?? null"
            @update:model-value="(value) => (widget.particleType = value)"
          />
        </div>
        <div class="col">
          <particle-field-select
            :address="resolvedParticleAddress"
            :model-value="widget.particleField ?? null"
            :particle-type="widget.particleType ?? null"
            @update:model-value="(value) => (widget.particleField = value)"
          />
        </div>
      </div>
      <common-text class="q-mb-sm" variant="title2">Display</common-text>
      <div class="q-col-gutter-sm q-mb-sm row">
        <div class="col-6">
          <schema-form-value
            v-model="widget.fontSize"
            :schema="{
              type: 'integer',
              title: 'Font Size (px)',
              optional: true,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
            v-model="widget.fontWeight"
            :schema="{
              type: 'string',
              title: 'Font Weight',
              enum: TextWeightModel.options,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
            v-model="widget.prefix"
            :schema="{
              type: 'string',
              title: 'Prefix',
              optional: true,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
            v-model="widget.suffix"
            :schema="{
              type: 'string',
              title: 'Suffix',
              optional: true,
            }"
          />
        </div>
      </div>
    </div>
  </div>
</template>
