<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'number' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const resolved = Number(value)
  if (Number.isNaN(resolved)) {
    return undefined
  }

  return resolved
}

function format(value: unknown) {
  if (typeof value !== 'number') {
    return ''
  }

  return String(value)
}
</script>

<template>
  <schema-form-input
    :form
    :format
    input-type="number"
    :model-value="modelValue"
    :path
    :resolve
    :schema
    schema-type="number"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>
