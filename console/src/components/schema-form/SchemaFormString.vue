<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
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
  <schema-form-input
    autogrow
    :form
    :format
    input-type="text"
    :model-value="modelValue"
    :path
    :resolve
    :schema
    schema-type="str"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  />
</template>
