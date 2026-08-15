<script lang="ts" setup>
import { getWidgetInfo } from '@/workspace'
import type { Widget } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
}>()

// Hovering the title turns it into a field there and then, the same offer the widget's own
// header makes, and clicking into it is what makes the offer a real edit.
let isEditingName = $ref(false)
let isNameHovered = $ref(false)
const isNameOffered = $computed(() => isEditingName || isNameHovered)
</script>

<template>
  <div class="p-4">
    <div class="mb-2 flex items-center whitespace-nowrap">
      <c-text
        variant="title1"
        @pointerenter="isNameHovered = true"
        @pointerleave="isNameHovered = false"
      >
        <c-inline-name-edit
          v-if="isNameOffered || widget.name !== ''"
          :claim="isEditingName"
          :editing="isNameOffered"
          :name="widget.name"
          @rename="(value: string) => (widget.name = value)"
          @update:editing="(value: boolean) => (isEditingName = value)"
        />
        <!-- An unnamed widget titles its dialog with the kind's own name. -->
        <template v-else>{{ getWidgetInfo(widget.type).name }}</template>
      </c-text>
    </div>
    <slot />
  </div>
</template>
