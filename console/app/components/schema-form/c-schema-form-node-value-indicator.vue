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

// Embedded, the field sits in the run of a sentence where a heavier mark would read as part of
// the text rather than as the field's own edge.
const widthClass = $computed(() => (form.embedded ? 'w-0.5' : 'w-[3px]'))
</script>

<template>
  <c-tooltip :disabled="error == null" :text="error ?? undefined">
    <!-- A box rounded like the control it marks, filled and then cut to a narrow strip, so the
    outside follows the corners away while the cut leaves the inside a straight line. Filled
    rather than stroked, since a stroke curves on both of its edges. -->
    <div class="h-full overflow-hidden" :class="widthClass">
      <div
        class="h-full w-[calc(var(--ui-radius)*1.5)] rounded-l-[calc(var(--ui-radius)*1.5)]"
        :class="backgroundColorClass"
      />
    </div>
  </c-tooltip>
</template>
