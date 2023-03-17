<template>
  <template v-if="resolved == null">
    Unable to resolve schema definition: {{ JSON.stringify(schema) }}
  </template>
  <template v-else-if="typeof resolved === 'boolean'"></template>
  <template v-else-if="resolved.type === 'integer'">
    <schema-form-integer
      :model-value="modelValue"
      :path="path"
      :schema="(resolved as any)"
      @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
    />
  </template>
  <template v-else-if="resolved.type === 'number'">
    <schema-form-number
      :model-value="modelValue"
      :path="path"
      :schema="(resolved as any)"
      @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
    />
  </template>
  <template v-else-if="resolved.type === 'string'">
    <schema-form-string
      :model-value="modelValue"
      :path="path"
      :schema="(resolved as any)"
      @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
    />
  </template>
  <template v-else-if="resolved.type === 'object'">
    <schema-form-object
      :model-value="modelValue"
      :path="path"
      :schema="(resolved as any)"
      @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
    />
  </template>
</template>

<script lang="ts" setup>
import SchemaFormInteger from '@/components/SchemaFormInteger.vue'
import SchemaFormNumber from '@/components/SchemaFormNumber.vue'
import SchemaFormObject from '@/components/SchemaFormObject.vue'
import SchemaFormString from '@/components/SchemaFormString.vue'
import { Schema, SchemaPath, useSchemaForm } from '@/json-schema'

const {
  modelValue,
  schema,
  path = [],
} = defineProps<{
  modelValue: unknown
  schema: Schema
  path?: SchemaPath
}>()

defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()
const resolved = form.resolve(schema)
</script>
