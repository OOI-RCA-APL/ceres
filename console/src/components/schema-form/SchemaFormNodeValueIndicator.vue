<script lang="ts" setup>
import { SchemaForm, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))
</script>

<template>
  <div
    :class="[
      $style.root,
      isDefined ? 'bg-primary' : 'bg-grey',
      isDefined && $style.defined,
      isRequired && $style.required,
    ]"
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
</style>
