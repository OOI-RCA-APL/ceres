<script lang="ts" setup>
import { useSchemaForm } from '@/schema-form'
import type { SchemaObject, SchemaPath } from '@/schema-form'

const { schema } = defineProps<{
  schema: SchemaObject
}>()

let modelValue = $(defineModel<unknown>('modelValue', { required: true }))

const path: SchemaPath = []
const form = useSchemaForm({
  value: () => modelValue,
  onUpdate: (value: unknown) => {
    modelValue = value as any
  },
  schema: () => schema,
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
