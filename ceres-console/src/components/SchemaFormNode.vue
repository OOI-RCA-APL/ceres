<template>
  <template v-if="resolved == null">
    Unable to resolve schema definition: {{ JSON.stringify(schema) }}
  </template>
  <template v-else-if="typeof resolved === 'boolean'"></template>
  <template v-else-if="true">
    <div class="col-grow items-center relative-position row">
      <template v-if="resolved.type === 'boolean'">
        <schema-form-boolean
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <template v-else-if="resolved.type === 'integer'">
        <schema-form-integer
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <template v-else-if="resolved.type === 'number'">
        <schema-form-number
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <template v-else-if="resolved.type === 'string'">
        <schema-form-string
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <template v-else-if="resolved.type === 'array'">
        <schema-form-array
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <template v-else-if="resolved.type === 'object'">
        <schema-form-object
          class="col-grow"
          :model-value="modelValue"
          :path="path"
          :schema="(resolved as any)"
          @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
        />
      </template>
      <schema-form-node-toggle
        class="absolute-top-left"
        :model-value="modelValue"
        :path="path"
        @update:model-value="(modelValue) => $emit('update:modelValue', modelValue)"
      />
    </div>
  </template>
</template>

<script lang="ts" setup>
import SchemaFormArray from '@/components/SchemaFormArray.vue'
import SchemaFormBoolean from '@/components/SchemaFormBoolean.vue'
import SchemaFormInteger from '@/components/SchemaFormInteger.vue'
import SchemaFormNodeToggle from '@/components/SchemaFormNodeToggle.vue'
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
  schema: Schema | null
  path?: SchemaPath
}>()

defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()
const resolved = $computed(() => (schema ? form.resolve(schema) : null))
const isRequired = $computed(() => form.isRequired(path))
</script>
