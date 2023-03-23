<template>
  <schema-form-input
    :form="form"
    :format="format"
    input-type="text"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :schema="schema"
    schema-type="String"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>

<script lang="ts" setup>
import SchemaFormInput from '@/components/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  return String(value)
}

function format(value: unknown) {
  if (typeof value !== 'string') {
    return ''
  }

  return value
}
</script>
