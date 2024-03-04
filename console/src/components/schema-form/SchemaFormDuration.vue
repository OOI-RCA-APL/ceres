<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { displayDuration, parseDuration } from '@/utilities'

const { modelValue, form, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'string'; format: 'duration' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const resolved = $computed(() => resolve(modelValue))
const defaultValue = $computed(() => resolve(form.getDefault(path)))
const resolvedOrDefault = $computed(() => resolved ?? defaultValue)

function resolve(value: unknown) {
  if (value == null) {
    return value
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
    return displayDuration(parseDuration(value as any))
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
  <schema-form-input
    :form
    :format
    input-type="text"
    :model-value="modelValue"
    :path
    :presets
    :resolve
    :schema
    schema-type="duration"
    suffix="second(s)"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  >
    <template v-if="resolvedOrDefault" #label-append>
      <span class="q-mx-xs">{{ '⸱' }}</span>
      <span>
        {{ displayDuration(resolvedOrDefault, { decimals: 3 }) }}
      </span>
    </template>
  </schema-form-input>
</template>
