<script lang="ts" setup>
import type { Schema, SchemaForm, SchemaPath } from '@/schema-form'

const modelValue = $(defineModel<unknown>({ required: true }))

defineProps<{
  form: SchemaForm
  schema: Schema
  path: SchemaPath
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
    return ''
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
  } catch {
    return ''
  }
}
</script>

<template>
  <c-schema-form-input
    v-model="modelValue"
    :form
    :format
    input-type="text"
    :path
    :resolve
    :resolve-text="resolveText"
    :schema
    schema-type="JSON"
  />
</template>
