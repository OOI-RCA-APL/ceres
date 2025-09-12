<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import SchemaFormNodeClearButton from '@/components/schema-form/SchemaFormNodeClearButton.vue'
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
    <div :class="[$style.row, 'items-center row']">
      <q-checkbox
        :aria-required="isRequired"
        :class="[$style.checkbox, 'monospace-sm']"
        dense
        :keep-color="true"
        :label
        :model-value="value"
        size="xs"
        @update:model-value="(modelValue) => emit('update:modelValue', resolve(modelValue))"
      />
      <q-space />
      <div>
        <schema-form-node-clear-button
          v-if="!isRequired && modelValue !== undefined"
          :class="$style.clearButton"
          @click="emit('update:modelValue', undefined)"
        />
      </div>
    </div>
    <common-text v-if="description" class="q-mt-xs q-pb-xs" variant="description">
      {{ description }}
    </common-text>
  </div>
</template>

<style module>
.root {
  padding-top: 8px;
  padding-left: 12px;
  padding-right: 12px;
  min-height: 40px;
  position: relative;
}

.row {
  min-height: 22px;
}

.clearButton {
  position: absolute;
  top: 9.5px;
  right: 11.75px;
}
</style>
