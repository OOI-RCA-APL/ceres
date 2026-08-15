<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'

import type { FilterValueInput } from '@/filters/definitions'
import icons from '@/icons'

const {
  input,
  autofocus = false,
  addressOptions = [],
} = defineProps<{
  input: FilterValueInput
  autofocus?: boolean

  /** The choices an address input offers, from the hosting view's scope. */
  addressOptions?: readonly string[]
}>()

let modelValue: unknown = $(defineModel<unknown>({ required: true }))

const emit = defineEmits<{
  /** The user finished the value, with Enter or by leaving the input. */
  commit: []
}>()

const text = $computed({
  get: () => (modelValue == null ? '' : String(modelValue)),
  set: (value: string) => {
    modelValue = value === '' ? null : value
  },
})

const placeholder = $computed(() => {
  if (input.type === 'duration') {
    return '1h'
  }
  if (input.type === 'date-time') {
    return 'time...'
  }

  return '...'
})

// Sized to its content so a chip hugs its value, and never narrower than the placeholder, which
// would otherwise be clipped on an empty condition.
const width = $computed(() => `${Math.max(placeholder.length, text.length + 1)}ch`)

const isMenuInput = $computed(() => input.type === 'enum' || input.type === 'address')

const menuItems = $computed<DropdownMenuItem[]>(() => {
  const options =
    input.type === 'enum' ? input.options : input.type === 'address' ? (addressOptions ?? []) : []

  return options.map((option) => ({
    label: option,
    onSelect: () => {
      modelValue = option
      emit('commit')
    },
  }))
})

function onIntegerBlur() {
  if (input.type !== 'integer' || modelValue == null) {
    return
  }

  let value = Math.floor(Number(modelValue))
  if (Number.isNaN(value)) {
    modelValue = null
    return
  }

  if (input.minimum != null && value < input.minimum) {
    value = input.minimum
  }
  if (input.exclusiveMaximum != null && value >= input.exclusiveMaximum) {
    value = input.exclusiveMaximum - 1
  }

  modelValue = value
}
</script>

<template>
  <c-dropdown-menu v-if="isMenuInput" :items="menuItems" size="sm">
    <button
      class="hover:text-primary flex cursor-pointer items-center gap-0.5 font-mono text-[11px]"
      :class="modelValue == null && 'text-muted'"
      type="button"
      @pointerdown.stop
    >
      {{ modelValue ?? 'choose...' }}
      <c-icon :name="icons.chevronDown" size="10" />
    </button>
  </c-dropdown-menu>
  <input
    v-else
    v-model="text"
    :autofocus="autofocus"
    class="bg-transparent font-mono text-[11px] outline-none"
    :placeholder="placeholder"
    spellcheck="false"
    :style="{ width }"
    type="text"
    @blur="(input.type === 'integer' ? onIntegerBlur() : undefined, emit('commit'))"
    @keydown.enter.prevent="emit('commit')"
    @keydown.stop
    @pointerdown.stop
  />
</template>
