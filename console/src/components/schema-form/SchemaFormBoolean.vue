<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'boolean' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
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
const label = $computed(() => form.getLabel(path))
const description = $computed(() => form.getDescription(path))
</script>

<template>
  <div :class="$style.root">
    <q-checkbox
      :aria-required="isRequired"
      :class="$style.checkbox"
      dense
      :keep-color="true"
      :label
      :model-value="value"
      size="xs"
      @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
    />
    <common-text v-if="description" class="q-mt-xs" variant="description">
      {{ description }}
    </common-text>
  </div>
</template>

<style module>
.root {
  padding-top: 8px;
  padding-left: 8px;
  min-height: 40px;
}
</style>
