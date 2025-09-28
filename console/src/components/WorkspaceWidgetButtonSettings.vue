<script lang="ts" setup>
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import Procedure from '@/components/Procedure.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ButtonWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

const engine = useEngine()

const title = $computed(() => widget.name?.trim() || 'Button')
const possibleComponents = $computed(() =>
  engine.components.all.filter(
    (current) => current.procedures.filter((current) => current.type === 'action').length > 0
  )
)

const possibleAddresses = $computed(() =>
  possibleComponents.map((component) => component.address.toString())
)

const component = $computed(() =>
  widget.address != null ? engine.components.get(widget.address) : null
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
  if (widget.address == null || widget.action == null) {
    return null
  }

  return engine.components.getAction(widget.address, widget.action)
})
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ title }}</common-text>
    <div class="q-col-gutter-sm q-mb-sm row">
      <div class="col-6 col-xs-12">
        <schema-form-value
          :model-value="widget.address?.toString()"
          :schema="{
            type: 'string',
            title: 'Address',
            enum: possibleAddresses,
            optional: true,
          }"
          @update:model-value="
            (value: string) => (widget.address = value ? Address.parse(value) : null)
          "
        />
      </div>
      <div class="col-6 col-xs-12">
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
      <div class="col-6 col-xs-12">
        <schema-form-value
          v-model="widget.label"
          :schema="{
            type: 'string',
            title: 'Label',
            optional: true,
          }"
        />
      </div>
    </div>
    <procedure
      v-if="action != null"
      v-model:arguments="widget.arguments"
      :address="widget.address"
      :procedure="action"
    />
  </div>
</template>
