<script lang="ts" setup>
import SchemaFormAddressSelector from '@/components/schema-form/SchemaFormAddressSelector.vue'
import SchemaFormAny from '@/components/schema-form/SchemaFormAny.vue'
import SchemaFormArray from '@/components/schema-form/SchemaFormArray.vue'
import SchemaFormBoolean from '@/components/schema-form/SchemaFormBoolean.vue'
import SchemaFormDate from '@/components/schema-form/SchemaFormDate.vue'
import SchemaFormDateTime from '@/components/schema-form/SchemaFormDateTime.vue'
import SchemaFormDuration from '@/components/schema-form/SchemaFormDuration.vue'
import SchemaFormEnum from '@/components/schema-form/SchemaFormEnum.vue'
import SchemaFormInteger from '@/components/schema-form/SchemaFormInteger.vue'
import SchemaFormNodeToggle from '@/components/schema-form/SchemaFormNodeToggle.vue'
import SchemaFormNumber from '@/components/schema-form/SchemaFormNumber.vue'
import SchemaFormObject from '@/components/schema-form/SchemaFormObject.vue'
import SchemaFormString from '@/components/schema-form/SchemaFormString.vue'
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
const isRequired = $computed(() => form.getRequired(path))
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

function isFormat(format: string) {
  if (schema == null) {
    return false
  }

  if (typeof schema === 'boolean') {
    return false
  }

  if (schema.format === format) {
    return true
  }

  if (schema.anyOf) {
    return schema.anyOf.some((option) => typeof option === 'object' && option.format === format)
  }
}

function update(value: unknown) {
  emit('update:modelValue', value)
}
</script>

<template>
  <template v-if="schema == null">
    <div>Unable to resolve schema definition at path: {{ JSON.stringify(path) }}</div>
  </template>
  <template v-else>
    <div class="relative-position">
      <template v-if="typeof schema === 'boolean'">
        <schema-form-any v-bind="forward" @update:model-value="update" />
      </template>
      <template v-else-if="schema.enum != null">
        <schema-form-enum v-bind="forward" @update:model-value="update" />
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
        <schema-form-date-time
          v-if="isFormat('date-time')"
          v-bind="forward"
          @update:model-value="update"
        />
        <schema-form-date
          v-else-if="isFormat('date')"
          v-bind="forward"
          @update:model-value="update"
        />
        <schema-form-duration
          v-else-if="isFormat('duration')"
          v-bind="forward"
          @update:model-value="update"
        />
        <schema-form-address-selector
          v-else-if="isFormat('address-selector')"
          v-bind="forward"
          @update:model-value="update"
        />
        <schema-form-string v-else v-bind="forward" @update:model-value="update" />
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
        v-if="!isRequired"
        class="absolute-top-left"
        :form
        :model-value="modelValue"
        :path
        @update:model-value="update"
      />
    </div>
  </template>
</template>
