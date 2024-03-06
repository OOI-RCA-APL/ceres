<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import moment from 'moment'

const { modelValue } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: string | undefined): void
}>()

const pattern = 'YYYY-MM-DD'
const valueOrNow = $computed(() => moment.utc(resolve(modelValue ?? moment.utc())))

function resolve(value: unknown) {
  if (value == null) {
    return value
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

  return resolved
}

const presets = [
  {
    label: 'Today (UTC)',
    factory: () => resolve(moment.utc()),
  },
  {
    label: 'Yesterday (UTC)',
    factory: () => resolve(moment.utc().subtract(1, 'day')),
  },
  {
    label: '-1 Day',
    factory: () => resolve(valueOrNow.subtract(1, 'day')),
  },
  {
    label: '+1 Day',
    factory: () => resolve(valueOrNow.add(1, 'day')),
  },
  {
    label: '-1 Week',
    factory: () => resolve(valueOrNow.subtract(7, 'days')),
  },
  {
    label: '+1 Week',
    factory: () => resolve(valueOrNow.add(7, 'days')),
  },
  {
    label: '-1 Month',
    factory: () => resolve(valueOrNow.add(30, 'days')),
  },
  {
    label: '+1 Month',
    factory: () => resolve(valueOrNow.add(30, 'days')),
  },
  {
    label: '-1 Year',
    factory: () => resolve(valueOrNow.subtract(365, 'days')),
  },
  {
    label: '+1 Year',
    factory: () => resolve(valueOrNow.add(365, 'days')),
  },
]
</script>

<template>
  <schema-form-input
    :form
    :format
    input-type="text"
    :model-value="modelValue"
    :path
    :presets
    :resolve
    :schema
    schema-type="date"
    suffix="UTC"
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  />
</template>
