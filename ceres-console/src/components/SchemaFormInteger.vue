<template>
  <div>
    <q-input
      :aria-required="required"
      dense
      filled
      label-slot
      :model-value="value"
      type="number"
      @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
    >
      <template #label>
        <schema-form-node-input-label v-if="title" :label="title" type="Integer" />
      </template>
    </q-input>
  </div>
</template>

<script lang="ts" setup>
import SchemaFormNodeInputLabel from '@/components/SchemaFormNodeInputLabel.vue'
import { SchemaObject, SchemaPath, useSchemaForm } from '@/json-schema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  schema: SchemaObject & { type: 'integer' }
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

  return Math.floor(resolved)
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

const required = $computed(() => form.isRequired(path))
const title = $computed(() => form.getTitle(path))
</script>
