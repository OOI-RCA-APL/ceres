<script lang="ts" setup>
import { useSchemaForm } from '@/schema-form'
import type { SchemaFormAlign, SchemaObject, SchemaPath } from '@/schema-form'

const {
  schema,
  embedded = false,
  showType = true,
  align = 'start',
} = defineProps<{
  schema: SchemaObject

  /** Draw the field inline, for a value edited in the run of something else. */
  embedded?: boolean
  /** Draw the value's type after its label, off where the label already says enough. */
  showType?: boolean
  /** Where the label and control sit across the field's width. */
  align?: SchemaFormAlign
}>()

let modelValue = $(defineModel<unknown>('modelValue', { required: true }))

const path: SchemaPath = []
const form = useSchemaForm({
  value: () => modelValue,
  onUpdate: (value: unknown) => {
    modelValue = value as any
  },
  schema: () => schema,
  embedded: () => embedded,
  showTypes: () => showType,
  align: () => align,
})
</script>

<template>
  <c-schema-form-node
    :form
    :model-value="form.value"
    :path
    @update:model-value="(value) => (form.value = value as any)"
  />
</template>
