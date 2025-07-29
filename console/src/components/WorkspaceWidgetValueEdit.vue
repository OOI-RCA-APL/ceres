<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import WorkspaceWidgetValue from '@/components/WorkspaceWidgetValue.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { ValueWidget, TextWeightModel } from '@/workspace'

const { widget } = $defineProps<{
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
          <schema-form-base
            v-model="widget.particleAddress"
            :schema="{
              type: 'string',
              title: 'Address',
              enum: engine.components.all.flatMap((current) => [
                current.address.toString(),
                current.address.all().toString(),
              ]),
              optional: true,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-base
            v-model="widget.particleType"
            :schema="{
              type: 'string',
              title: 'Type',
              optional: true,
            }"
          />
        </div>
        <div class="col">
          <schema-form-base
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
          <schema-form-base
            v-model="widget.fontSize"
            :schema="{
              type: 'integer',
              title: 'Font Size (px)',
              default: 20,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-base
            v-model="widget.fontWeight"
            :schema="{
              type: 'string',
              title: 'Font Weight',
              enum: TextWeightModel.options,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-base
            v-model="widget.prefix"
            :schema="{
              type: 'string',
              title: 'Prefix',
              optional: true,
            }"
          />
        </div>
        <div class="col-6">
          <schema-form-base
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
