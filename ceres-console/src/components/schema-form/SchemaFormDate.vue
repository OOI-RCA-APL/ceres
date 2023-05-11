<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import moment from 'moment'

defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: string | undefined): void
}>()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  const parsed = moment(value, 'YYYY-MM-DD')
  if (parsed.isValid()) {
    return parsed.format('YYYY-MM-DD')
  }

  return undefined
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
    :form="form"
    :format="format"
    input-type="text"
    mask="####-##-##"
    :model-value="modelValue"
    :path="path"
    :resolve="resolve"
    :schema="schema"
    schema-type="date"
    stack-label
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  />
</template>
