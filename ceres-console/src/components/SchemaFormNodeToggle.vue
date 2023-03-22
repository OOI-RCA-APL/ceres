<template>
  <div
    :class="[
      'self-schema-form-node-toggle-root',
      isDefined ? 'bg-primary' : 'bg-grey',
      isDefined && 'self-schema-form-node-toggle-root-defined',
      isRequired && 'self-schema-form-node-toggle-root-required',
    ]"
    @click="onClick"
  />
</template>

<script lang="ts" setup>
import { SchemaPath, useSchemaForm } from '@/json-schema'

const { modelValue, path = [] } = defineProps<{
  modelValue: unknown
  path?: SchemaPath
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const form = useSchemaForm()
const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

function onClick() {
  if (isDefined) {
    if (!isRequired) {
      emit('update:modelValue', undefined)
    }
  } else {
    const schema = form.getSchema(path)
    if (schema) {
      emit('update:modelValue', form.getDefault(schema))
    }
  }
}
</script>

<style scoped>
.self-schema-form-node-toggle-root {
  border-bottom-left-radius: 4px;
  border-top-left-radius: 4px;
  height: 100%;
  opacity: 0.65;
  transition: opacity 0.5s;
  width: 4px;
}

.self-schema-form-node-toggle-root:hover {
  opacity: 1;
}

.self-schema-form-node-toggle-root-required {
  /* border: 0.5px dashed white; */
  /* opacity: 0.5; */
  background-color: transparent !important;
}

:not(.self-schema-form-node-toggle-root-defined),
:not(.self-schema-form-node-toggle-root-required) {
  cursor: pointer;
}
</style>
