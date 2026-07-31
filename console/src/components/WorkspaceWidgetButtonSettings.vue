<script lang="ts" setup>
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ButtonAction, ColorModel, ButtonStylingModel, useWorkspace } from '@/workspace'

const { button } = defineProps<{
  button: ButtonAction
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedAddress = $computed(() => {
  const resolved = workspace.resolveAddress(button.address)
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
  if (button.action !== undefined) {
    if (!possibleActions.includes(button.action)) {
      button.action = undefined
    }
  }
})
</script>

<template>
  <div class="q-col-gutter-sm row">
    <div class="col-sm-6 col-xs-12">
      <workspace-address-select
        :model-value="button.address?.toString() ?? null"
        @update:model-value="
          (value) => (button.address = value != null && value !== '' ? Address.parse(value) : null)
        "
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.action"
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
        v-model="button.label"
        :schema="{
          type: 'string',
          title: 'Label',
          optional: true,
        }"
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.tooltip"
        :schema="{
          type: 'string',
          title: 'Tooltip',
          optional: true,
        }"
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.color"
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
        v-model="button.styling"
        :schema="{
          type: 'string',
          title: 'Style',
          enum: ButtonStylingModel.options,
          optional: true,
        }"
      />
    </div>
    <div class="col-12">
      <!-- Both of these change what pressing the button does rather than how it looks, so they sit
      together under the fields that describe it. -->
      <q-checkbox v-model="button.confirm" dense label="Ask before running" size="xs" />
    </div>
    <div class="col-12">
      <q-checkbox
        v-model="button.locked"
        dense
        label="Run with the arguments it was left with"
        size="xs"
      />
    </div>
  </div>
</template>
