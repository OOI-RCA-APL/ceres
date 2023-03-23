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
        <span :style="{ opacity: 0.5 }"> ⸱ {{ schemaType }}</span>
      </div>
    </template>
  </q-input>
</template>

<script lang="ts" setup>
import { Schema, SchemaForm, SchemaPath } from '@/schema-form'
import { debounce } from 'quasar'
import { watch, watchEffect } from 'vue'

const {
  modelValue,
  form,
  path,
  resolve,
  format = String,
} = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: Schema
  path: SchemaPath
  inputType: 'text' | 'number'
  schemaType: string
  resolve: (value: unknown) => unknown
  format: (value: unknown) => string | null
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

const resolvedModelValue = $computed(() => resolve(modelValue))
if (resolvedModelValue !== modelValue) {
  emit('update:modelValue', resolvedModelValue)
}

let text = $ref(format(resolvedModelValue))
let isFocused = $ref(false)

const required = $computed(() => form.getRequired(path))
const title = $computed(() => form.getTitle(path))

// Whenever the input is not focused and model value is changes, update the text.
watchEffect(() => {
  if (!isFocused) {
    text = format(resolve(modelValue))
  }
})

// Whenever the input is focused and the text resolves to a valid value, update the model value.
watch(
  () => text,
  debounce(() => {
    if (isFocused) {
      const resolvedValue = resolve(text)
      if (resolvedValue !== modelValue && resolvedValue !== undefined) {
        emit('update:modelValue', resolvedValue)
      }
    }
  }, 50)
)

// Run when the input is focused.
function onFocus() {
  isFocused = true
}

// Run when the input loses focus.
function onBlur() {
  // Resolve the text value and emit the result whenever the input loses focus.
  if (resolvedModelValue !== undefined) {
    const resolvedValue = resolve(text)
    emit('update:modelValue', resolvedValue)
  }
  // Write the resolved value to the text input.
  text = format(resolvedModelValue)
  isFocused = false
}

// Run when the user hits backspace.
function onBackspace() {
  // If the value is not required, the text is empty and the user hits backspace one more time,
  // emit undefined to remove the value.
  if (text === '' && !required) {
    emit('update:modelValue', undefined)
  }
}
</script>
