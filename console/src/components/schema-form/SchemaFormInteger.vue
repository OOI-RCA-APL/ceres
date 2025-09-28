<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue = $(defineModel<unknown>({ required: true }))

const { form } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'number' }
  path: SchemaPath
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

  return Math.floor(resolved)
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
    v-model="modelValue"
    :form
    :format
    input-type="number"
    :path
    :resolve
    :schema
    schema-type="integer"
  />
</template>
