<script lang="ts" setup>
import { upperFirst } from 'lodash-es'
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { useWorkspace } from '@/workspace'
import type { ProceduresWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ProceduresWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedProcedureAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.procedureAddress)
  return resolved == null ? null : Address.parse(resolved)
})

const component = $computed(() =>
  resolvedProcedureAddress == null ? null : engine.components.get(resolvedProcedureAddress),
)

// No type chosen lists both, the widget being a way into a component's procedures before it is
// a filter over them.
const procedures = $computed(
  () =>
    component?.procedures.filter(
      (procedure) => widget.procedureType == null || procedure.type === widget.procedureType,
    ) ?? [],
)

const selected = $computed(() => {
  if (widget.procedureName == null) {
    return null
  }

  return procedures.find((procedure) => procedure.name === widget.procedureName) ?? null
})

const typePlural = $computed(() => {
  switch (widget.procedureType) {
    case 'action':
      return 'actions'
    case 'query':
      return 'queries'
    default:
      return 'procedures'
  }
})

watchEffect(() => {
  if (selected == null && procedures.length > 0) {
    widget.procedureName = procedures[0]?.name ?? null
  }
})
</script>

<template>
  <div>
    <div class="flex gap-2">
      <c-workspace-address-select
        class="grow"
        :model-value="widget.procedureAddress?.toString() ?? null"
        @update:model-value="
          (value) =>
            (widget.procedureAddress = value != null && value !== '' ? Address.parse(value) : null)
        "
      />
      <!-- Optional so it can be cleared back to listing both, which is what it opens on. -->
      <c-schema-form-value
        v-model="widget.procedureType"
        class="w-[140px]"
        :schema="{
          type: 'string',
          title: 'Procedure Type',
          enum: ['action', 'query'],
          optional: true,
        }"
      />
    </div>
    <c-separator class="my-2" />
    <template v-if="procedures.length > 0">
      <c-schema-form-value
        v-model="widget.procedureName"
        class="mb-3"
        :schema="{
          type: 'string',
          title: upperFirst(widget.procedureType ?? 'procedure'),
          enum: procedures.map((procedure) => procedure.name),
        }"
      />
      <c-procedure
        v-if="selected != null && component != null"
        :key="selected.name"
        :address="component.address"
        :procedure="selected"
      />
    </template>
    <div v-else class="flex items-center justify-center p-2 opacity-50">
      <c-text variant="body2">No available {{ typePlural }} were found.</c-text>
    </div>
  </div>
</template>
