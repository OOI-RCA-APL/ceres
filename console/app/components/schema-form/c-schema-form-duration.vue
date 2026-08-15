<script lang="ts" setup>
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { approximateDuration, parseDuration } from '@/time'

const modelValue = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'duration' }
  path: SchemaPath
}>()

const resolved = $computed(() => resolve(modelValue))
const defaultValue = $computed(() => resolve(form.getDefault(path)))
const resolvedOrDefault = $computed(() => resolved ?? defaultValue)

function resolve(value: unknown) {
  if (value == null) {
    return undefined
  }

  try {
    return parseDuration(value as any).toISOString()
  } catch {
    return undefined
  }
}

function format(value: unknown) {
  if (value == null) {
    return ''
  }

  try {
    return approximateDuration(parseDuration(value as any))
  } catch {
    return ''
  }
}

const presets = [
  { label: '1 minute', factory: () => resolve('1m') },
  { label: '5 minutes', factory: () => resolve('5m') },
  { label: '15 minutes', factory: () => resolve('15m') },
  { label: '30 minutes', factory: () => resolve('30m') },
  { label: '1 hour', factory: () => resolve('1h') },
  { label: '12 hours', factory: () => resolve('12h') },
  { label: '1 day', factory: () => resolve('1d') },
  { label: '1 week', factory: () => resolve('7d') },
  { label: '1 month', factory: () => resolve('30d') },
  { label: '1 year', factory: () => resolve('365d') },
]
</script>

<template>
  <c-schema-form-input
    v-model="modelValue"
    :form
    :format
    input-type="text"
    :path
    :presets
    :resolve
    :schema
    schema-type="duration"
  >
    <template v-if="resolvedOrDefault" #label-append>
      <span class="mx-1">{{ '⸱' }}</span>
      <span>
        {{ approximateDuration(resolvedOrDefault, { decimals: 3 }) }}
      </span>
    </template>
  </c-schema-form-input>
</template>
