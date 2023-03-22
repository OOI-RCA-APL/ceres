<template>
  <schema-form-input
    :format="format"
    input-type="number"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :schema="schema"
    schema-type="Number"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>

<script lang="ts" setup>
import SchemaFormInput from '@/components/SchemaFormInput.vue'
import { SchemaObject, SchemaPath } from '@/json-schema'

const { modelValue } = defineProps<{
  modelValue: unknown
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
