<script lang="ts" setup>
import type { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const { form, schema, path } = defineProps<{
  form: SchemaForm
  schema: SchemaObject & { type: 'object' }
  path: SchemaPath
}>()

const isRequired = $computed(() => form.getRequired(path))

const object = $computed(() => {
  if (modelValue == null) {
    return modelValue
  }

  if (typeof modelValue !== 'object' || Array.isArray(modelValue)) {
    return undefined
  }

  return modelValue as Record<string, unknown>
})

const properties = $computed(() => Object.keys(schema.properties ?? {}))

if (object !== modelValue) {
  modelValue = object
}

function withAssigned(property: string, subvalue: unknown) {
  if (object == null) {
    return object
  }

  const keys = Object.keys(schema.properties ?? {})
  const entries = keys
    .map((current) => [current, current === property ? subvalue : object[current]])
    .filter(([, value]) => value !== undefined)

  return Object.fromEntries(entries)
}

function onUpdate(property: string, subvalue: unknown) {
  modelValue = withAssigned(property, subvalue)
}
</script>

<template>
  <c-schema-form-composite
    :form
    :model-value="object"
    :path
    @update:model-value="(value) => (modelValue = value)"
  >
    <div
      v-if="object"
      class="flex flex-col gap-1"
      :class="(path.length > 0 || !isRequired) && 'p-2'"
    >
      <div v-for="property in properties" :key="property">
        <c-schema-form-node
          :form
          :model-value="object[property]"
          :path="[...path, property]"
          @update:model-value="(subvalue) => onUpdate(property, subvalue)"
        />
      </div>
      <div v-if="properties.length" :style="{ height: '2px' }" />
    </div>
  </c-schema-form-composite>
</template>
