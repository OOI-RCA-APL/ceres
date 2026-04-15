<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { utc } from '@/time'

let modelValue = $(defineModel<unknown>({ required: true }))

defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date' }
  path: SchemaPath
}>()

const pattern = 'YYYY-MM-DD'
const valueOrNow = $computed(() => utc(resolve(modelValue ?? utc())))

function resolve(value: unknown): string | undefined {
  if (value == null) {
    return undefined
  }

  const parsed = utc(value as any, pattern)
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
    factory: () => resolve(utc()),
  },
  {
    label: 'Yesterday (UTC)',
    factory: () => resolve(utc().subtract(1, 'day')),
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
    v-model="modelValue"
    :form
    :format
    input-type="text"
    :path
    :presets
    :resolve
    :schema
    schema-type="date"
    suffix="UTC"
  />
</template>
