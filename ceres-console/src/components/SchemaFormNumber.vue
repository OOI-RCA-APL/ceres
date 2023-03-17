<template>
  <div>
    <q-input
      :aria-required="required"
      class="self-input"
      :clearable="!required"
      dense
      filled
      input-class="self-input"
      label-slot
      :model-value="value"
      type="number"
      @clear="emit('update:modelValue', undefined)"
      @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
    >
      <template #label>
        <div class="row">
          <span class="q-mr-xs">
            {{ label }} <span v-if="required" style="opacity: 0.65">*</span>
          </span>
          <span :style="{ opacity: 0.5, fontSize: undefined }"> (float)</span>
        </div>
      </template>
    </q-input>
  </div>
</template>

<script lang="ts" setup>
import { SchemaPath, useSchemaForm, SchemaObject } from '@/json-schema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  schema: SchemaObject & { type: 'number' }
  path?: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  if (typeof value === 'string') {
    if (value.trim() === '') {
      return undefined
    }
  }

  const resolved = Number(value)
  if (Number.isNaN(resolved)) {
    return undefined
  }

  return resolved
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

const required = $computed(() => form.isRequired(path))
const label = $computed(() => form.getLabel(path))
</script>
