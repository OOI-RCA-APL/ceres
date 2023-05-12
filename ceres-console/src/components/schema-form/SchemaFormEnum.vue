<script lang="ts" setup>
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'
import { Plain } from '@/utilities'
import { isEqual } from 'lodash'

const { form, schema, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { enum: Plain[] }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const title = $computed(() => form.getLabel(path))

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  for (const option of schema.enum) {
    if (isEqual(option, value)) {
      return value as Plain
    }
  }

  return undefined
}

function format(value: unknown) {
  try {
    const result = JSON.stringify(value)
    if (result.startsWith('[') || result.startsWith('{')) {
      return result
    }
  } catch {
    // Ignore and just return the string value.
  }

  return String(value)
}
</script>

<template>
  <q-select
    dense
    filled
    label-slot
    :model-value="resolve(modelValue)"
    :option-label="format"
    :options="schema.enum"
    options-dense
    @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
  >
    <template #label>
      <div class="monospace-md row">
        <span>{{ title }}</span>
        <span :class="$style.labelExtra">
          <span class="q-mx-xs">{{ '⸱' }}</span>
          <span>enum</span>
        </span>
      </div>
    </template>
  </q-select>
</template>

<style module>
.labelExtra {
  opacity: 0.5;
}
</style>
