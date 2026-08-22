<script lang="ts" setup>
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'boolean' }
  path: SchemaPath
}>()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  return Boolean(value)
}

const resolved: unknown = $computed(() => resolve(modelValue))
if (resolved !== modelValue) {
  modelValue = resolved
}

const isRequired = $computed(() => form.getRequired(path))
const label = $computed(() => form.getLabel(path))
const description = $computed(() => form.getDescription(path))
</script>

<template>
  <div>
    <c-schema-form-node-label
      :align="form.align"
      :label="label"
      schema-type="bool"
      :show-type="form.showTypes"
    />
    <!-- As tall as a field of the same size, so a boolean beside one lines up with it. -->
    <!-- Spacers rather than a justification, since the clear button holds the end of the row and
    would be carried along with the switch. -->
    <div class="flex min-h-8 items-center">
      <div v-if="form.align !== 'start'" class="grow" />
      <c-switch
        :aria-required="isRequired"
        :model-value="resolved === true"
        size="sm"
        @update:model-value="(value) => (modelValue = resolve(value))"
      />
      <div v-if="form.align !== 'end'" class="grow" />
      <c-schema-form-node-clear-button
        v-if="!isRequired && modelValue !== undefined"
        :embedded="form.embedded"
        @click="modelValue = undefined"
      />
    </div>
    <c-text v-if="description && !form.embedded" class="mt-1 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
