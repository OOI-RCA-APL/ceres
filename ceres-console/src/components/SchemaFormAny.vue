<template>
  <schema-form-input
    :form="form"
    :format="format"
    input-type="text"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :schema="schema"
    schema-type="JSON"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>

<script lang="ts" setup>
import SchemaFormInput from '@/components/SchemaFormInput.vue'
import { Schema, SchemaForm, SchemaPath } from '@/schema-form'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: Schema
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

function resolve(value: unknown): unknown {
  if (typeof value !== 'string') {
    return value
  }
  if (value.trim() === '') {
    return undefined
  }

  try {
    return JSON.parse(value) ?? value
  } catch {
    return value
  }
}

function format(value: unknown) {
  if (value === undefined) {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }

  try {
    return JSON.stringify(value) ?? ''
  } catch {}

  return ''
}
</script>
