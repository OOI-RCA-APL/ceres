<script lang="ts" setup>
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'boolean' }
  path: SchemaPath
}>()

function resolve(value: unknown) {
  if (value == null) {
    return value
  }

  return Boolean(value)
}

const resolved: unknown = $computed(() => resolve(modelValue))
if (resolved !== modelValue) {
  modelValue = resolved
}

const isRequired = $computed(() => form.getRequired(path))
const label = $computed(() => form.getLabel(path))
const description = $computed(() => form.getDescription(path))
</script>

<template>
  <div class="relative min-h-10 px-3 pt-2">
    <div class="flex min-h-[22px] items-center">
      <c-checkbox
        :aria-required="isRequired"
        :model-value="resolved === true"
        size="sm"
        :ui="{ label: 'font-mono text-[11px]' }"
        @update:model-value="(value) => (modelValue = resolve(value))"
      >
        <template #label>{{ label }}</template>
      </c-checkbox>
      <div class="grow" />
      <c-schema-form-node-clear-button
        v-if="!isRequired && modelValue !== undefined"
        @click="modelValue = undefined"
      />
    </div>
    <c-text v-if="description" class="mt-1 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
