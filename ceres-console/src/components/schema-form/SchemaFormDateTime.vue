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

const inputPattern = 'YYYY-MM-DD HH:mm:ss.SSS'
const outputPattern = 'YYYY-MM-DD HH:mm:ss.SSS+00:00'

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const parsed = moment.utc(value, inputPattern)
  if (parsed.isValid()) {
    return parsed.format(outputPattern)
  }

  return undefined
}

function format(value: unknown) {
  let resolved = resolve(value)
  if (resolved == null) {
    return ''
  }

  if (/.[0]+$/.test(resolved)) {
    resolved = resolved.slice(0, resolved.lastIndexOf('.')).trim()
  }
  if (/:[0]+$/.test(resolved)) {
    resolved = resolved.slice(0, resolved.lastIndexOf(':')).trim()
  }
  if (resolved.endsWith(' 00:00')) {
    resolved = resolved.slice(0, resolved.lastIndexOf(' ')).trim()
  }

  return resolved
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
    suffix="UTC"
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  />
</template>
