<script lang="ts" setup>
import { Schema, SchemaForm, SchemaPath } from '@/schema-form'
import { QInput, debounce } from 'quasar'
import { watch } from 'vue'

const {
  modelValue,
  form,
  path,
  resolve,
  format = String,
  resolveText: resolveTextOriginal,
  mask = undefined,
  autogrow = false,
  suffix = undefined,
} = defineProps<{
  modelValue: unknown
  form: SchemaForm
  schema: Schema
  path: SchemaPath
  inputType: 'text' | 'number' | 'date'
  schemaType: string
  resolve: (value: unknown) => unknown
  resolveText?: (text: string) => unknown
  format: (value: unknown) => string
  mask?: string
  autogrow?: boolean
  suffix?: string
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', value: unknown): void
}>()

let input = $ref<QInput | null>(null)

const resolvedModelValue = $computed(() => resolve(modelValue))
if (resolvedModelValue !== modelValue) {
  emit('update:modelValue', resolvedModelValue)
}

let text = $ref(format(resolvedModelValue))
let isFocused = $ref(false)

const isRequired = $computed(() => form.getRequired(path))
const title = $computed(() => form.getLabel(path))
const resolveText = $computed(() => resolveTextOriginal ?? resolve)

// Whenever the input is focused and the text resolves to a valid value, update the model value.
watch(
  () => text,
  debounce(() => {
    if (isFocused) {
      const resolvedValue = resolveText(text)
      if (resolvedValue !== undefined) {
        emit('update:modelValue', resolvedValue)
      }
    }
  }, 0)
)

// Whenever the model value changes and the input is not focused, update the text.
watch(
  () => modelValue,
  () => {
    if (!isFocused) {
      text = format(resolve(modelValue))
    }
  },
  { immediate: true }
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

<template>
  <q-input
    ref="input"
    v-model="text"
    :aria-required="isRequired"
    :autogrow="autogrow"
    dense
    filled
    input-class="monospace-md"
    label-slot
    :mask="mask"
    :suffix="suffix"
    :type="inputType"
    @blur="onBlur"
    @focus="onFocus"
    @keydown.backspace="onBackspace"
  >
    <template #label>
      <div class="monospace-md row">
        <span>{{ title }}</span>
        <span :class="$style.labelExtra">
          <span class="q-mx-xs">{{ '⸱' }}</span>
          <span>{{ schemaType }}</span>
          <slot name="label-append" />
        </span>
      </div>
    </template>
    <template v-if="$slots.prepend" #prepend>
      <slot name="prepend" />
    </template>
    <template v-if="$slots.append" #append>
      <slot name="append" />
    </template>
  </q-input>
</template>

<style module>
.labelExtra {
  opacity: 0.5;
}
</style>
