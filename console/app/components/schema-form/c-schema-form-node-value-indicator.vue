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
    <div :class="[$style.root, backgroundColorClass]" />
  </c-tooltip>
</template>

<style module>
.root {
  border-bottom-left-radius: 50px;
  border-top-left-radius: 50px;
  height: calc(100% - 1.2px);
  margin-top: 0.6px;
  width: 2px;
}
</style>
