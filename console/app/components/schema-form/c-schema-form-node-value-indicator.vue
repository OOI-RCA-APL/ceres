<script lang="ts" setup>
import { isType } from '@/schema-form'
import type { SchemaForm, SchemaPath } from '@/schema-form'

const modelValue = $(defineModel<unknown>({ required: true }))

const { form, path } = defineProps<{
  form: SchemaForm
  path: SchemaPath
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

const isContainer = $computed(() => {
  const schema = form.getSchema(path)
  return schema != null && (isType(schema, 'object') || isType(schema, 'array'))
})

// A bar drawn around a whole form repeats what its fields already say, and an embedded field
// is drawn in the run of a sentence where one reads as clutter. A field standing on its own
// is a root as much as a form is, so the depth alone does not decide this.
const isHidden = $computed(() => form.embedded || (isRequired && path.length === 0 && isContainer))
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
