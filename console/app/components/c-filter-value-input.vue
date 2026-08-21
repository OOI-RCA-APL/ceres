<script lang="ts" setup>
import { nextTick, watchEffect } from 'vue'

import type { FilterValueInput } from '@/filters/definitions'
import type { SchemaObject } from '@/schema-form'

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

/** The condition's value as a schema, so a filter edits it with the same field a form would.

The bar names the condition itself, so nothing here carries a title, and the value is always
optional: a condition is added before it is filled in.
*/
const schema = $computed<SchemaObject>(() => {
  switch (input.type) {
    case 'date-time':
      return { type: 'string', format: 'date-time', optional: true }
    case 'duration':
      return { type: 'string', format: 'duration', optional: true }
    case 'address':
      return { type: 'string', format: 'address', optional: true, examples: [...addressOptions] }
    case 'enum':
      return { type: 'string', enum: [...input.options], optional: true }
    case 'connection':
      return { type: 'string', format: 'connection', optional: true }
    case 'integer':
      return {
        type: 'integer',
        optional: true,
        minimum: input.minimum,
        exclusiveMaximum: input.exclusiveMaximum,
      }
    default:
      return { type: 'string', optional: true }
  }
})

let root = $ref<HTMLElement | null>(null)

function focusField() {
  const field = root?.querySelector<HTMLElement>('input, textarea, [role="combobox"], button')
  field?.focus()

  // A value that is chosen rather than typed opens its menu, the condition having just been added
  // to pick from it. A typed field is left with the caret in it.
  if (
    field != null &&
    !(field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement)
  ) {
    field.click()
  }
}

// Taken here rather than left to the attribute, which a browser acts on only while first
// loading the page. These arrive when a condition is added, long after that.
watchEffect(() => {
  if (autofocus) {
    void nextTick(focusField)
  }
})

const clipboardKeys = new Set(['c', 'x', 'v'])

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    emit('commit')
    return
  }

  // What is typed stays in the value. The clipboard keys carry on to the bar, which acts on whole
  // conditions when the field has no text of its own in hand.
  if (!((event.metaKey || event.ctrlKey) && clipboardKeys.has(event.key))) {
    event.stopPropagation()
  }
}

/** Whether focus has left the field entirely, rather than moved within it. */
function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget
  if (next instanceof Node && root?.contains(next)) {
    return
  }

  emit('commit')
}
</script>

<template>
  <!-- Pointer events are held back so a click here is not a click on the chip. -->
  <span
    ref="root"
    class="inline-flex items-center"
    @focusout="onFocusOut"
    @keydown="onKeydown"
    @pointerdown.stop
  >
    <c-schema-form-value v-model="modelValue" embedded :schema />
  </span>
</template>
