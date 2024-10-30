<script lang="ts" setup>
import moment from 'moment'

import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'date-time' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: string | null | undefined): void
}>()

const inputPattern = 'YYYY-MM-DD HH:mm:ss.SSS'
const outputPattern = 'YYYY-MM-DD HH:mm:ss.SSS+00:00'

const resolved = $computed(() => resolve(modelValue))
const valueOrNow = $computed(() => moment.utc(resolved ?? moment.utc()))

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

const presets = [
  {
    label: 'Now',
    factory: () => resolve(moment.utc()),
  },
  {
    label: 'Today (UTC)',
    factory: () => resolve(moment.utc().set({ hour: 0, minute: 0, second: 0, millisecond: 0 })),
  },
  {
    label: 'Yesterday (UTC)',
    factory: () =>
      resolve(
        moment.utc().subtract(1, 'day').set({ hour: 0, minute: 0, second: 0, millisecond: 0 })
      ),
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
    :form
    :format
    input-type="text"
    :model-value="modelValue"
    :path
    :presets
    :resolve
    :schema
    schema-type="date-time"
    suffix="UTC"
    @update:model-value="(modelValue: any) => emit('update:modelValue', modelValue)"
  />
</template>
