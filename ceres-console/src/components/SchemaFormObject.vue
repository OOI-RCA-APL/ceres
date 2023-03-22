<template>
  <schema-form-composite :model-value="object" :path="path">
    <div v-if="object" class="column q-col-gutter-sm q-pa-sm">
      <div v-for="property in Object.keys(schema.properties ?? {})" :key="property">
        <schema-form-node
          :model-value="object[property]"
          :path="[...path, property]"
          @update:model-value="(subvalue) => onUpdate(property, subvalue)"
        />
      </div>
    </div>
  </schema-form-composite>
</template>

<script lang="ts" setup>
import SchemaFormComposite from '@/components/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import { SchemaObject, SchemaPath } from '@/json-schema'

const { modelValue, schema } = defineProps<{
  modelValue: unknown
  schema: SchemaObject & { type: 'object' }
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const object = $computed(() => {
  if (modelValue == null) {
    return modelValue
  }

  if (typeof modelValue !== 'object' || Array.isArray(modelValue)) {
    return undefined
  }

  return modelValue as Record<string, unknown>
})

if (object !== modelValue) {
  emit('update:modelValue', object)
}

function withAssigned(property: string, subvalue: unknown) {
  if (object == null) {
    return object
  }

  const keys = Object.keys(schema.properties ?? {})
  const entries = keys.map((current) => [
    current,
    current === property ? subvalue : object[current],
  ])

  return Object.fromEntries(entries)
}

function onUpdate(property: string, subvalue: unknown) {
  emit('update:modelValue', withAssigned(property, subvalue))
}
</script>
