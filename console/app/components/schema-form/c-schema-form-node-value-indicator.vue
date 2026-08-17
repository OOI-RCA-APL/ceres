<script lang="ts" setup>
import type { SchemaForm, SchemaPath } from '@/schema-form'

const modelValue = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  path: SchemaPath
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))
const isHidden = $computed(() => isRequired && path.length === 0)
const error = $computed(() => form.getValidationErrorMessage(path))
const backgroundColorClass = $computed(() => {
  if (error != null) {
    return 'bg-error'
  }
  if (isHidden) {
    return 'bg-transparent'
  }
  if (isDefined) {
    return 'bg-primary'
  }

  return 'bg-accented'
})
</script>

<template>
  <c-tooltip :disabled="error == null" :text="error ?? undefined">
    <div
      class="mt-[0.6px] h-[calc(100%-1.2px)] w-0.5 rounded-l-[50px]"
      :class="backgroundColorClass"
    />
  </c-tooltip>
</template>
