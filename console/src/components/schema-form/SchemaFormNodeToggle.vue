<script lang="ts" setup>
import { SchemaForm, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))

function toggle() {
  if (isDefined) {
    if (!isRequired) {
      emit('update:modelValue', undefined)
    }
  } else {
    const schema = form.getSchema(path)
    if (schema) {
      emit('update:modelValue', form.getInitialValue(schema))
    }
  }
}
</script>

<template>
  <div
    :class="[
      $style.root,
      isDefined ? 'bg-primary' : 'bg-grey',
      isDefined && $style.defined,
      isRequired && $style.required,
    ]"
    @click="toggle"
  />
</template>

<style module>
.root {
  border-bottom-left-radius: 4px;
  border-top-left-radius: 4px;
  height: 100%;
  transition: opacity 0.5s;
  width: 4px;
}

.root:hover {
  opacity: 1;
}

.required {
  background-color: transparent !important;
}

.root:not(.defined),
.root:not(.required) {
  cursor: pointer;
}
</style>
