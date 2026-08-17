<script lang="ts" setup>
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const modelValue = $(defineModel<unknown>({ required: true }))

defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string' }
  path: SchemaPath
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

<template>
  <c-schema-form-input
    v-model="modelValue"
    autogrow
    :form
    :format
    input-type="text"
    :path
    :resolve
    :schema
    schema-type="str"
  />
</template>
