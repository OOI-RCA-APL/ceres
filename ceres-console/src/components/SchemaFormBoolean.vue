<template>
  <div>
    <q-checkbox
      :aria-required="required"
      class="q-ml-xs self-schema-form-boolean-root"
      :keep-color="true"
      :label="label"
      :model-value="value"
      size="xs"
      @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
    />
  </div>
</template>

<script lang="ts" setup>
import { SchemaObject, SchemaPath, useSchemaForm } from '@/json-schema'

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

  return Boolean(value)
}

const value = $computed(() => resolve(modelValue))
if (value !== modelValue) {
  emit('update:modelValue', value)
}

const required = $computed(() => form.isRequired(path))
const label = $computed(() => form.getTitle(path))
</script>

<style scoped>
.self-schema-form-boolean-root {
  min-height: 40px;
}
</style>
