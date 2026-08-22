<script lang="ts" setup>
import type { SchemaFormAlign } from '@/schema-form'

const { element = 'div', align = 'start' } = defineProps<{
  /** The field's title, as the form resolved it. */
  label?: string
  /** The value's type in the form's vocabulary, drawn after the label unless types are hidden. */
  schemaType: string
  /** Whether the type is drawn, off for a form that reads as plain settings. */
  showType?: boolean
  /** Where the label sits across the field's width. */
  align?: SchemaFormAlign
  /** `label` for a field a click should focus, which a bare control has no use for. */
  element?: 'div' | 'label'
}>()

defineEmits<{ click: [MouseEvent] }>()

const alignments: Record<SchemaFormAlign, string> = {
  start: 'justify-start',
  center: 'justify-center',
  end: 'justify-end',
}
</script>

<template>
  <!-- The dot takes only a trailing margin, the row's own gap carrying the side toward the label,
  so the two sides of it come out even. -->
  <component
    :is="element"
    class="mb-1 flex items-baseline gap-1"
    :class="alignments[align]"
    @click="$emit('click', $event)"
  >
    <c-text inline variant="mono-sm">{{ label }}</c-text>
    <c-text v-if="showType || $slots['label-append']" class="text-muted" inline variant="mono-sm">
      <template v-if="showType">
        <span class="mr-1">{{ '⸱' }}</span>
        <span>{{ schemaType }}</span>
      </template>
      <slot name="label-append" />
    </c-text>
  </component>
</template>
