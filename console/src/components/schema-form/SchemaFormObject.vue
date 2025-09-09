<script lang="ts" setup>
import SchemaFormComposite from '@/components/schema-form/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/schema-form/SchemaFormNode.vue'
import { SchemaForm, SchemaObject, SchemaPath } from '@/schema-form'

const { modelValue, form, schema, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: SchemaObject & { type: 'object' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
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
  emit('update:modelValue', object)
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
  emit('update:modelValue', withAssigned(property, subvalue))
}
</script>

<template>
  <schema-form-composite
    :form
    :model-value="object"
    :path
    @update:model-value="(modelValue) => emit('update:modelValue', modelValue)"
  >
    <div
      v-if="object"
      :class="['column q-col-gutter-xs', (path.length > 0 || !isRequired) && 'q-pa-sm']"
    >
      <div v-for="property in properties" :key="property">
        <schema-form-node
          :form
          :model-value="object[property]"
          :path="[...path, property]"
          @update:model-value="(subvalue) => onUpdate(property, subvalue)"
        />
      </div>
      <div v-if="properties.length" :style="{ height: '2px' }" />
    </div>
  </schema-form-composite>
</template>
