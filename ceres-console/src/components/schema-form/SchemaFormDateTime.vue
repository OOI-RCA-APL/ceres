<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import moment from 'moment'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date-time' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: string | undefined): void
}>()

const pattern = 'YYYY-MM-DD HH:mm:ss.SSS'

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const parsed = moment.utc(value, pattern)
  if (parsed.isValid()) {
    return parsed.format(pattern)
  }

  return undefined
}

function format(value: unknown) {
  const resolved = resolve(value)
  if (typeof resolved !== 'string') {
    return ''
  }

  return resolved.replace(/[.:0 ]+$/, '')
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
    :schema="schema"
    schema-type="date-time"
    stack-label
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  />
</template>
