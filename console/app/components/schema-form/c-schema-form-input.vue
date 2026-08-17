<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { createReusableTemplate } from '@vueuse/core'
import { watch } from 'vue'

import { CInput, CTextarea } from '#components'
import icons from '@/icons'
import type { Schema, SchemaForm, SchemaPath } from '@/schema-form'

type Preset = {
  label: string
  factory: () => unknown
}

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

// The trailing controls render either inside the field's own slot or beside it, so they are
// declared once here and placed twice below.
const [DefineTrailing, ReuseTrailing] = createReusableTemplate()

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
  embeddedColumns = 6,
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

  /** The narrowest a embedded field goes, in characters. It sizes to its text from there, so this
  is a floor for an empty field rather than a width. */
  embeddedColumns?: number
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

// The steppers are dropped because a number here is typed, and the field is sized to its text,
// which leaves them sitting on the digits rather than beside them.
const fieldClass = $computed(() =>
  [
    'font-mono [appearance:textfield]',
    '[&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none',
    form.embedded
      ? 'text-[9px] px-0 py-0 min-w-(--field-columns) [field-sizing:content]'
      : 'text-xs',
  ].join(' '),
)

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
  <div :class="form.embedded && 'contents'">
    <!-- Embedded leaves the naming to whatever the field is sitting in, which is the only reason
    a field would be drawn without it. -->
    <label
      v-if="!form.embedded"
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
    <!-- Embedded lays the trailing controls out beside the field rather than over it. Nuxt UI
    positions its own trailing slot absolutely and clears it with padding, which cannot hold once
    the controls are a suffix and two buttons wide. -->
    <define-trailing>
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
        :embedded="form.embedded"
        @click="onClear"
      />
    </define-trailing>
    <div :class="form.embedded ? 'flex min-w-0 items-center gap-0.5' : 'contents'">
      <component
        :is="autogrow ? CTextarea : CInput"
        ref="input"
        :aria-required="isRequired"
        autoresize
        :class="form.embedded ? 'w-auto font-mono' : 'w-full font-mono'"
        :model-value="text"
        :placeholder="format(defaultValue)"
        :rows="1"
        :size="form.embedded ? 'xs' : 'sm'"
        spellcheck="false"
        :style="form.embedded ? { '--field-columns': `${embeddedColumns}ch` } : {}"
        :type="autogrow ? undefined : inputType"
        :ui="{ base: fieldClass }"
        :variant="form.embedded ? 'none' : undefined"
        @blur="onBlur"
        @focus="onFocus"
        @keydown.backspace="onBackspace"
        @update:model-value="onInput"
      >
        <template v-if="!form.embedded" #trailing>
          <reuse-trailing />
        </template>
      </component>
      <reuse-trailing v-if="form.embedded" />
    </div>
    <c-text v-if="description && !form.embedded" class="mt-1 ml-3 pb-1" variant="description">
      {{ description }}
    </c-text>
  </div>
</template>
