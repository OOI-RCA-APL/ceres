<script lang="ts" setup>
import { SchemaForm, SchemaPath } from '@/schema-form'

const { modelValue, form, path } = $defineProps<{
  modelValue: unknown
  form: SchemaForm
  path: SchemaPath
}>()

const isDefined = $computed(() => modelValue !== undefined)
const isRequired = $computed(() => form.getRequired(path))
const isHidden = $computed(() => isRequired && path.length === 0)
const error = $computed(() => form.getValidationErrorMessage(path))
const backgroundColorClass = $computed(() => {
  if (error != null) {
    return 'bg-negative'
  }
  if (isHidden) {
    return 'bg-transparent'
  }
  if (isDefined) {
    return 'bg-primary'
  }

  return 'bg-grey'
})
</script>

<template>
  <div
    :class="[
      $style.root,
      backgroundColorClass,
      isDefined && $style.defined,
      isHidden && $style.hidden,
    ]"
  >
    <q-tooltip v-if="error != null" class="bg-negative text-white">
      {{ error }}
    </q-tooltip>
  </div>
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
</style>
