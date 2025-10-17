<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import WorkspaceWidgetValue from '@/components/WorkspaceWidgetValue.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ValueWidget, TextWeightModel } from '@/workspace'

const { widget } = defineProps<{
  widget: ValueWidget
}>()

const engine = useEngine()
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
          <schema-form-value
            :model-value="widget.particleAddress?.toString()"
            :schema="{
              type: 'string',
              title: 'Address',
              enum: engine.components.all.flatMap((current) => [
                current.address.toString(),
                current.address.all().toString(),
              ]),
              optional: true,
            }"
            @update:model-value="(value: string) => {
              widget.particleAddress = value ? AddressSelector.parse(value) : null
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-value
            v-model="widget.particleType"
            :schema="{
              type: 'string',
              title: 'Type',
              optional: true,
            }"
          />
        </div>
        <div class="col">
          <schema-form-value
            v-model="widget.particleField"
            :schema="{
              type: 'string',
              title: 'Field',
              optional: true,
            }"
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
