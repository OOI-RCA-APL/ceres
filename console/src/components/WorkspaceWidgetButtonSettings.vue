<script lang="ts" setup>
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import Procedure from '@/components/Procedure.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ButtonWidget, ColorModel, ButtonStylingModel, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const title = $computed(() => widget.name?.trim() || 'Button')

const resolvedAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.address)
  return resolved == null ? null : Address.parse(resolved)
})

const component = $computed(() =>
  resolvedAddress != null ? engine.components.get(resolvedAddress) : null
)

const possibleActions = $computed(
  () =>
    component?.procedures
      .filter((procedure) => procedure.type === 'action')
      .map((procedure) => procedure.name) ?? []
)

watchEffect(() => {
  if (widget.action !== undefined) {
    if (!possibleActions.includes(widget.action)) {
      widget.action = undefined
    }
  }
})

const action = $computed(() => {
  if (resolvedAddress == null || widget.action == null) {
    return null
  }

  return engine.components.getAction(resolvedAddress, widget.action)
})
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ title }}</common-text>
    <div class="q-col-gutter-sm q-mb-sm row">
      <div class="col-sm-6 col-xs-12">
        <workspace-address-select
          :model-value="widget.address?.toString() ?? null"
          @update:model-value="
            (value) =>
              (widget.address = value != null && value !== '' ? Address.parse(value) : null)
          "
        />
      </div>
      <div class="col-sm-6 col-xs-12">
        <schema-form-value
          v-model="widget.action"
          :schema="{
            type: 'string',
            title: 'Action',
            enum: possibleActions,
            optional: true,
          }"
        />
      </div>
      <div class="col-sm-6 col-xs-12">
        <schema-form-value
          v-model="widget.label"
          :schema="{
            type: 'string',
            title: 'Label',
            optional: true,
          }"
        />
      </div>
      <div class="col-sm-6 col-xs-12">
        <schema-form-value
          v-model="widget.tooltip"
          :schema="{
            type: 'string',
            title: 'Tooltip',
            optional: true,
          }"
        />
      </div>
      <div class="col-sm-6 col-xs-12">
        <schema-form-value
          v-model="widget.color"
          :schema="{
            type: 'string',
            title: 'Color',
            enum: ColorModel.options,
            optional: true,
          }"
        />
      </div>
      <div class="col-sm-6 col-xs-12">
        <schema-form-value
          v-model="widget.styling"
          :schema="{
            type: 'string',
            title: 'Style',
            enum: ButtonStylingModel.options,
            optional: true,
          }"
        />
      </div>
    </div>
    <procedure
      v-if="action != null && resolvedAddress != null"
      v-model:arguments="widget.arguments"
      :address="resolvedAddress"
      :procedure="action"
    />
  </div>
</template>
