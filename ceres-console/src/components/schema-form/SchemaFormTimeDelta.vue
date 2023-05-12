<script lang="ts" setup>
import SchemaFormInput from '@/components/schema-form/SchemaFormInput.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { displayTimeDelta, parseTimeDelta } from '@/utilities'

const { modelValue } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'number'; format: 'time-delta' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const resolved = $computed(() => resolve(modelValue))

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  try {
    return parseTimeDelta(value as any).asSeconds()
  } catch {
    return undefined
  }
}

function format(value: unknown) {
  const resolved = resolve(value)
  if (resolved == null) {
    return ''
  }

  return String(resolved)
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
    schema-type="time-delta"
    suffix="second(s)"
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  >
    <template v-if="resolved != null" #label-append>
      <span class="q-mx-xs">{{ '⸱' }}</span>
      <span>
        {{ displayTimeDelta(resolved, { decimals: 3 }) }}
      </span>
    </template>
  </schema-form-input>
</template>
