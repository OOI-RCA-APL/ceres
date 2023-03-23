<template>
  <template v-if="schema == null">
    Unable to resolve schema definition at path: {{ JSON.stringify(path) }}
  </template>
  <template v-else-if="true">
    <div class="col-grow items-center relative-position row">
      <template v-if="typeof schema === 'boolean'">
        <schema-form-any v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('boolean')">
        <schema-form-boolean v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('integer')">
        <schema-form-integer v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('number')">
        <schema-form-number v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('string')">
        <schema-form-string v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('array')">
        <schema-form-array v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="is('object')">
        <schema-form-object v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else>
        <schema-form-any v-bind="forward" @update:model-value="update" />
      </template>
      <schema-form-node-toggle
        class="absolute-top-left"
        :form="form"
        :model-value="modelValue"
        :path="path"
        @update:model-value="update"
      />
    </div>
  </template>
</template>

<script lang="ts" setup>
import SchemaFormAny from '@/components/SchemaFormAny.vue'
import SchemaFormArray from '@/components/SchemaFormArray.vue'
import SchemaFormBoolean from '@/components/SchemaFormBoolean.vue'
import SchemaFormInteger from '@/components/SchemaFormInteger.vue'
import SchemaFormNodeToggle from '@/components/SchemaFormNodeToggle.vue'
import SchemaFormNumber from '@/components/SchemaFormNumber.vue'
import SchemaFormObject from '@/components/SchemaFormObject.vue'
import SchemaFormString from '@/components/SchemaFormString.vue'
import { isType, SchemaForm, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const schema = $computed(() => form.getSchema(path))
const forward = $computed(() => ({
  class: 'col-grow',
  form,
  modelValue,
  path,
  schema: schema as any,
}))

function is(type: string) {
  if (schema == null) {
    return false
  }

  return isType(schema, type)
}

function update(value: unknown) {
  emit('update:modelValue', value)
}
</script>
