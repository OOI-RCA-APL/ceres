<script lang="ts" setup>
import { QInput } from 'quasar'
import { watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import SchemaFormNodeClearButton from '@/components/schema-form/SchemaFormNodeClearButton.vue'
import icons from '@/icons'
import { Schema, SchemaForm, SchemaPath } from '@/schema-form'

type Preset = {
  label: string
  factory: () => unknown
}

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const {
  form,
  path,
  resolve,
  format = String,
  resolveText: resolveTextOriginal,
  mask = undefined,
  autogrow = false,
  suffix = undefined,
  presets = undefined,
  noClearOnEmpty = false,
} = defineProps<{
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
  presets?: Preset[]
  noClearOnEmpty?: boolean
}>()

let input = $ref<QInput | null>(null)

const resolvedModelValue = $computed(() => resolve(modelValue))
if (resolvedModelValue !== modelValue) {
  modelValue = resolvedModelValue
}

let text = $ref(format(resolvedModelValue))
let isFocused = $ref(false)

const isRequired = $computed(() => form.getRequired(path))
const description = $computed(() => form.getDescription(path))
const defaultValue = $computed(() => form.getDefault(path))
const title = $computed(() => form.getLabel(path))
const resolveText = $computed(() => resolveTextOriginal ?? resolve)

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

// Run when the input element is focused.
function onFocus() {
  isFocused = true
}

// Run when the input element loses focus.
function onBlur() {
  // Resolve the text value and emit the result whenever the input loses focus.
  if (resolvedModelValue !== undefined) {
    const resolvedValue = resolveText(text)
    modelValue = resolvedValue
    // Write the resolved value to the text input.
    text = format(resolvedValue)
  } else {
    // Write the undefined value to the text input.
    text = format(undefined)
  }

  isFocused = false
}

// Run when the user hits backspace with the input element selected.
function onBackspace() {
  // If the value is not required, the text is empty and the user hits backspace one more time,
  // emit `undefined` to remove the value, so long as `noClearOnEmpty` is not set.
  if (!noClearOnEmpty && text === '' && !isRequired) {
    modelValue = undefined
  }
}

// Run when the user hits the clear button.
async function onClear() {
  modelValue = undefined
  text = ''
  input?.focus() // Re-focus the input after the clear button is hit.
}

// Run when the user types text into the input element.
function onInputModelUpdate(value: string) {
  // Store the raw text value.
  text = value

  // If the text resolves to a valid value, emit an update to the model value.
  const resolvedValue = resolveText(text)
  if (resolvedValue !== undefined) {
    modelValue = resolvedValue
  }
}

</script>

<template>
  <div>
    <q-input
      ref="input"
      :aria-required="isRequired"
      :autogrow
      dense
      filled
      input-class="monospace-md"
      label-slot
      :mask
      :model-value="text"
      :placeholder="format(defaultValue)"
      spellcheck="false"
      :suffix
      :type="inputType"
      @blur="onBlur"
      @focus="onFocus"
      @keydown.backspace="onBackspace"
      @update:model-value="onInputModelUpdate"
    >
      <template #label>
        <div class="monospace-md no-wrap row">
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
      <template #append>
        <slot name="append" />
        <q-btn
          v-if="presets"
          color="primary"
          flat
          :icon="icons.settings"
          round
          size="8px"
          tabindex="-1"
        >
          <q-menu dense transition-duration="100" transition-hide="scale" transition-show="scale">
            <q-list bordered class="rounded-borders" dense>
              <q-item
                v-for="preset in presets"
                :key="preset.label"
                clickable
                @click="modelValue = preset.factory()"
              >
                <q-item-section>
                  <q-item-label>{{ preset.label }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
        <schema-form-node-clear-button
          v-if="!isRequired && modelValue !== undefined"
          @click="onClear"
        />
      </template>
    </q-input>
    <common-text v-if="description" :class="$style.description" variant="description">
      {{ description }}
    </common-text>
  </div>
</template>

<style module>
.labelExtra {
  opacity: 0.5;
}

.description {
  margin-top: 4px;
  margin-left: 12px;
  padding-bottom: 4px;
}
</style>
