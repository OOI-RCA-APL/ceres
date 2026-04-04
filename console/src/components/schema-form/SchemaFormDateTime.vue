<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { utc } from '@/time'

let modelValue = $(defineModel<unknown>({ required: true }))

defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date-time' }
  path: SchemaPath
}>()

const outputFormat = 'YYYY-MM-DD HH:mm:ss.SSSZ'
const inputFormats = [
  outputFormat,
  'YYYY-MM-DD HH:mm:ss.SSS',
  'YYYY-MM-DD HH:mm:ss',
  'YYYY-MM-DD HH:mm',
  'YYYY-MM-DD',
] as const

const resolved = $computed(() => resolve(modelValue))
const valueOrNow = $computed(() => utc(resolved ?? utc()))

function resolve(value: unknown): string | undefined {
  if (value == null) {
    return undefined
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const parsed = utc(value as any, inputFormats, false)
  if (parsed.isValid()) {
    return parsed.format(outputFormat)
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
  if (resolved.endsWith('+00:00')) {
    resolved = resolved.slice(0, resolved.lastIndexOf('+')).trim()
  }
  if (resolved.endsWith('Z')) {
    resolved = resolved.slice(0, resolved.lastIndexOf('Z')).trim()
  }

  return resolved
}

const presets = [
  {
    label: 'Now',
    factory: () => resolve(utc()),
  },
  {
    label: 'Today (UTC)',
    factory: () => resolve(utc().hour(0).minute(0).second(0).millisecond(0)),
  },
  {
    label: 'Yesterday (UTC)',
    factory: () => resolve(utc().subtract(1, 'day').hour(0).minute(0).second(0).millisecond(0)),
  },
  {
    label: '-1 Hour',
    factory: () => resolve(valueOrNow.subtract(1, 'hour')),
  },
  {
    label: '+1 Hour',
    factory: () => resolve(valueOrNow.add(1, 'hour')),
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
    factory: () => resolve(valueOrNow.subtract(7, 'days')),
  },
  {
    label: '+1 Month',
    factory: () => resolve(valueOrNow.add(7, 'days')),
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
    schema-type="date-time"
    suffix="UTC"
  />
</template>
