<template>
  <q-input
    v-model="text"
    :aria-required="isRequired"
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
import { watch } from 'vue'

const {
  modelValue,
  form,
  path,
  resolve,
  format = String,
  ...props
} = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: Schema
  path: SchemaPath
  inputType: 'text' | 'number'
  schemaType: string
  resolve: (value: unknown) => unknown
  resolveText?: (text: string) => unknown
  format: (value: unknown) => string
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

const isRequired = $computed(() => form.getRequired(path))
const title = $computed(() => form.getTitle(path))
const resolveText = $computed(() => props.resolveText ?? resolve)

// Whenever the model value changes and the input is not focused, update the text.
watch(
  () => modelValue,
  () => {
    if (!isFocused) {
      text = format(resolve(modelValue))
    }
  }
)

// Whenever the input is focused and the text resolves to a valid value, update the model value.
watch(
  () => text,
  debounce(() => {
    if (isFocused) {
      const resolvedValue = resolveText(text)
      if (resolvedValue !== undefined && resolvedValue !== modelValue) {
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
    const resolvedValue = resolveText(text)
    emit('update:modelValue', resolvedValue)
    // Write the resolved value to the text input.
    text = format(resolvedValue)
  } else {
    // Write the undefined value to the text input.
    text = format(undefined)
  }

  isFocused = false
}

// Run when the user hits backspace.
function onBackspace() {
  // If the value is not required, the text is empty and the user hits backspace one more time,
  // emit undefined to remove the value.
  if (text === '' && !isRequired) {
    emit('update:modelValue', undefined)
  }
}
</script>
