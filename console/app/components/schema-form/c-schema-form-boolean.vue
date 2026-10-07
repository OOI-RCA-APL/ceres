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
const error = $computed(() => form.getValidationErrorMessage(path))

// A value never set draws as neither on nor off, so an optional field is not read as false.
// A required one draws as off until it fails validation.
const isUnset = $computed(() => resolved === undefined && (!isRequired || error != null))

// The switch marks its own state and error, since the presence bar would sit notched into the
// track's round end.
const ui = $computed(() => {
  if (isUnset) {
    return {
      base: [
        'border-dashed data-[state=unchecked]:bg-transparent',
        error != null ? 'border-error' : 'border-accented opacity-60',
      ],
      thumb: 'invisible',
    }
  }

  return { base: error != null ? 'ring-2 ring-error' : undefined }
})
</script>

<template>
  <div>
    <c-schema-form-node-label
      :align="form.align"
      :label="label"
      schema-type="bool"
      :show-type="form.showTypes"
    />
    <!-- As tall as a field of the same size, so a boolean beside one lines up with it. -->
    <!-- Spacers rather than a justification, since the clear button holds the end of the row and
    would be carried along with the switch. -->
    <div class="flex min-h-8 items-center">
      <div v-if="form.align !== 'start'" class="grow" />
      <c-tooltip :disabled="error == null" :text="error ?? undefined">
        <c-switch
          :aria-required="isRequired"
          v-bind="isUnset ? { 'aria-checked': 'mixed' } : {}"
          :model-value="resolved === true"
          size="sm"
          :ui
          @update:model-value="(value) => (modelValue = resolve(value))"
        />
      </c-tooltip>
      <div v-if="form.align !== 'end'" class="grow" />
      <c-schema-form-node-clear-button
        v-if="!isRequired && modelValue !== undefined"
        :embedded="form.embedded"
        @click="modelValue = undefined"
      />
    </div>
    <c-description
      v-if="description && !form.embedded"
      class="mt-1 pb-1 text-[11px] text-muted"
      :text="description"
    />
  </div>
</template>
