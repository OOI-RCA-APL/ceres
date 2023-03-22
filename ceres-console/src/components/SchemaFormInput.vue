<template>
  <q-input
    v-model="text"
    :aria-required="required"
    dense
    filled
    label-slot
    :type="inputType"
    @blur="onBlur"
    @focus="onFocus"
    @keydown.backspace="onBackspace"
  >
    <template #label>
      <div class="row">
        <span class="q-mr-xs">{{ title }}</span>
        <span :style="{ opacity: 0.5, fontSize: undefined }"> ⸱ {{ schemaType }}</span>
      </div>
    </template>
  </q-input>
</template>

<script lang="ts" setup>
import { Schema, SchemaPath, useSchemaForm } from '@/json-schema'
import { debounce } from 'quasar'
import { watch, watchEffect } from 'vue'

const {
  modelValue,
  path,
  resolve,
  format = String,
} = defineProps<{
  modelValue: unknown
  schema: Schema
  path: SchemaPath
  inputType: 'text' | 'number'
  schemaType: string
  resolve: (value: unknown) => unknown
  format: (value: unknown) => string
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const resolved = $computed(() => resolve(modelValue))
if (resolved !== modelValue) {
  emit('update:modelValue', resolved)
}

const form = useSchemaForm()
let text = $ref(format(resolved))
let isFocused = $ref(false)

const required = $computed(() => form.getRequired(path))
const title = $computed(() => form.getTitle(path))

// Write to the text input when the model value is updated externally without focus.
watchEffect(() => {
  if (isFocused) {
    return
  }

  text = format(resolve(modelValue))
})

// Emit model value updates whenever we get a valid value.
watch(
  () => text,
  debounce(() => {
    const resolved = resolve(text)
    if (resolved !== modelValue && resolved !== undefined) {
      emit('update:modelValue', resolved)
    }
  }, 50)
)

// Run when the input is focused.
function onFocus() {
  isFocused = true
}

// Run when the input loses focus.
function onBlur() {
  isFocused = false
  // Resolve the text value and emit the result whenever the input loses focus.
  const resolved = resolve(text)
  emit('update:modelValue', resolved)
  // Write the resolved value to the text input.
  text = format(resolved)
}

// Run when the user hits backspace.
function onBackspace() {
  // If the value is not required, the text is empty and the user hits backspace one more time,
  // emit undefined to remove the value.
  if (!required && text === '') {
    emit('update:modelValue', undefined)
  }
}
</script>
