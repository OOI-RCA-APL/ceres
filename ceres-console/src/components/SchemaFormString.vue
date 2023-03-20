<template>
  <q-input
    :aria-required="required"
    dense
    filled
    label-slot
    :model-value="value"
    outlined
    type="text"
    @clear="emit('update:modelValue', undefined)"
    @keydown.stop.backspace="onBackspace"
    @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
  >
    <template #label>
      <schema-form-node-input-label v-if="title" :label="title" type="String" />
    </template>
  </q-input>
</template>

<script lang="ts" setup>
import SchemaFormNodeInputLabel from '@/components/SchemaFormNodeInputLabel.vue'
import { Schema, SchemaPath, useSchemaForm } from '@/json-schema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  schema: Schema & { type: 'string' }
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

  return String(value)
}

function onBackspace() {
  if (!required && value === '') {
    emit('update:modelValue', undefined)
  }
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

const required = $computed(() => form.isRequired(path))
const title = $computed(() => form.getTitle(path))
</script>
