<template>
  <q-input
    :aria-required="required"
    :clearable="!required"
    dense
    filled
    label-slot
    :model-value="value"
    outlined
    type="text"
    @clear="emit('update:modelValue', undefined)"
    @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
  >
    <template #label>
      <div class="row">
        <span class="q-mr-xs">
          {{ label }} <span v-if="required" style="opacity: 0.65">*</span>
        </span>
        <span :style="{ opacity: 0.5, fontSize: undefined }"> (str)</span>
      </div>
    </template>
  </q-input>
</template>

<script lang="ts" setup>
import { Path, useSchemaForm } from '@/schema-form'
import { Schema } from 'jsonschema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  schema: Schema & { type: 'string' }
  path?: Path
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  const text = String(value)
  if (text === '') {
    return undefined
  }

  return text
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

const required = $computed(() => form.isRequired(path))
const label = $computed(() => form.getLabel(path))
</script>
