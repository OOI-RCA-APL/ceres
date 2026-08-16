<script lang="ts" setup>
import { CInput, CTextarea } from '#components'
import type { DropdownMenuItem } from '@nuxt/ui'
import { watch } from 'vue'

import icons from '@/icons'
import type { Schema, SchemaForm, SchemaPath } from '@/schema-form'

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
  format?: (value: unknown) => string
  autogrow?: boolean
  suffix?: string
  presets?: Preset[]
  noClearOnEmpty?: boolean
}>()

let input = $ref<{ inputRef?: HTMLInputElement; textareaRef?: HTMLTextAreaElement } | null>(null)

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

const presetItems = $computed<DropdownMenuItem[]>(() =>
  (presets ?? []).map((preset) => ({
    label: preset.label,
    onSelect: () => {
      modelValue = preset.factory()
    },
  })),
)

// While the input is focused the text is the user's, and the model only follows it. Once
// focus leaves, model updates flow back into the text.
watch(
  () => modelValue,
  () => {
    if (!isFocused) {
      text = format(resolve(modelValue))
    }
  },
  { immediate: true },
)

function onFocus() {
  isFocused = true
}

function onBlur() {
  // Normalize the text through the resolver so the input shows the canonical spelling.
  if (resolvedModelValue !== undefined) {
    const resolvedValue = resolveText(text)
    modelValue = resolvedValue
    text = format(resolvedValue)
  } else {
    text = format(undefined)
  }

  isFocused = false
}

function onBackspace() {
  // A backspace on an already-empty optional input removes the value entirely.
  if (!noClearOnEmpty && text === '' && !isRequired) {
    modelValue = undefined
  }
}

function onClear() {
  modelValue = undefined
  text = ''
  focusInput()
}

function focusInput() {
  input?.inputRef?.focus()
  input?.textareaRef?.focus()
}

function onInput(value: string | number) {
  text = String(value)

  // Emit only once the text resolves, so partial typing never writes garbage to the model.
  const resolvedValue = resolveText(text)
  if (resolvedValue !== undefined) {
    modelValue = resolvedValue
  }
}
</script>

<template>
  <div :class="form.compact && 'contents'">
    <!-- Compact leaves the naming to whatever the field is sitting in, which is the only reason
    a field would be drawn without it. -->
    <label
      v-if="!form.compact"
      class="mb-1 flex cursor-text items-baseline gap-1"
      @click="focusInput()"
    >
      <c-text element="span" variant="mono-sm">{{ title }}</c-text>
      <c-text class="text-muted" element="span" variant="mono-sm">
        <span class="mx-1">{{ '⸱' }}</span>
        <span>{{ schemaType }}</span>
        <slot name="label-append" />
      </c-text>
    </label>
    <!-- The imported components, not their names, a string here resolving only against locally
    registered ones and rendering an unknown element with no field in it. -->
    <component
      :is="autogrow ? CTextarea : CInput"
      ref="input"
      :aria-required="isRequired"
      autoresize
      :class="form.compact ? 'font-mono' : 'w-full font-mono'"
      :model-value="text"
      :placeholder="format(defaultValue)"
      :rows="1"
      :size="form.compact ? 'xs' : 'sm'"
      spellcheck="false"
      :type="autogrow ? undefined : inputType"
      :ui="{ base: form.compact ? 'font-mono text-[11px] px-0 py-0' : 'font-mono text-xs' }"
      :variant="form.compact ? 'none' : undefined"
      @blur="onBlur"
      @focus="onFocus"
      @keydown.backspace="onBackspace"
      @update:model-value="onInput"
    >
      <template #trailing>
        <c-text v-if="suffix" class="text-muted" element="span" variant="mono-xs">
          {{ suffix }}
        </c-text>
        <slot name="append" />
        <c-dropdown-menu v-if="presets" :items="presetItems" size="sm">
          <c-button
            color="neutral"
            :icon="icons.settings"
            size="xs"
            square
            tabindex="-1"
            variant="ghost"
          />
        </c-dropdown-menu>
        <c-schema-form-node-clear-button
          v-if="!isRequired && modelValue !== undefined"
          @click="onClear"
        />
      </template>
    </component>
    <c-text v-if="description && !form.compact" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
