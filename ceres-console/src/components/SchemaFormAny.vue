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
  return value
}

function resolveText(value: string): unknown {
  if (typeof value !== 'string') {
    return value
  }

  value = value.trim()
  if (value === '') {
    return undefined
  }

  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function format(value: unknown) {
  if (value === undefined) {
    return ''
  }

  try {
    return JSON.stringify(value) ?? ''
  } catch {}

  return ''
}
</script>

<template>
  <schema-form-input
    :form="form"
    :format="format"
    input-type="text"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :resolve-text="resolveText"
    :schema="schema"
    schema-type="JSON"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>
