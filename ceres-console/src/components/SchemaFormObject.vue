<template>
  <schema-form-composite :path="path" :value="object">
    <div v-if="object" class="column q-col-gutter-sm q-pa-sm">
      <div v-for="[property, subschema] in Object.entries(schema.properties ?? {})" :key="property">
        <schema-form-node
          :model-value="object[property]"
          :path="[...path, property]"
          :schema="subschema"
          @update:model-value="
            (subvalue) => $emit('update:modelValue', { ...object, [property]: subvalue })
          "
        />
      </div>
    </div>
  </schema-form-composite>
</template>

<script lang="ts" setup>
import SchemaFormComposite from '@/components/SchemaFormComposite.vue'
import SchemaFormNode from '@/components/SchemaFormNode.vue'
import { SchemaObject, SchemaPath } from '@/json-schema'

const {
  modelValue,
  schema,
  path = [],
} = defineProps<{
  modelValue: unknown
  schema: SchemaObject & { type: 'object' }
  path?: SchemaPath
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
</script>
