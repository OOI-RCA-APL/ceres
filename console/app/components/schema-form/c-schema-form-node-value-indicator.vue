<script lang="ts" setup>
import type { SchemaForm, SchemaPath } from '@/schema-form'

const modelValue = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  path: SchemaPath
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

// The bar says whether an optional value has been set, so a field that must have one has
// nothing to report.
const isHidden = $computed(() => isRequired && path.length === 0)
const error = $computed(() => form.getValidationErrorMessage(path))
const borderColorClass = $computed(() => {
  if (error != null) {
    return 'border-error'
  }
  if (isHidden) {
    return 'border-transparent'
  }
  if (isDefined) {
    return 'border-primary'
  }

  return 'border-accented'
})
</script>

<template>
  <c-tooltip :disabled="error == null" :text="error ?? undefined">
    <!-- Drawn as the left edge of a box rounded like the control it marks, so the mark follows
    the corners away rather than standing straight across them. Clipped to a constant width, so
    the inside stays a straight line while the outside curves. -->
    <div class="h-full w-0.5 overflow-hidden">
      <div
        class="h-full w-[calc(var(--ui-radius)*1.5)] rounded-l-[calc(var(--ui-radius)*1.5)] border-l-2"
        :class="borderColorClass"
      />
    </div>
  </c-tooltip>
</template>
