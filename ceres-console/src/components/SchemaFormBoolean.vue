<template>
  <q-checkbox
    :aria-required="isRequired"
    class="q-ml-xs self-schema-form-boolean-root"
    :keep-color="true"
    :label="label"
    :model-value="value"
    size="xs"
    @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
  />
</template>

<script lang="ts" setup>
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'boolean' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

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

const isRequired = $computed(() => form.getRequired(path))
const label = $computed(() => form.getTitle(path))
</script>

<style scoped>
.self-schema-form-boolean-root {
  min-height: 40px;
}
</style>
