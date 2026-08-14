<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import icons from '@/icons'
import { getWidgetInfo, Widget } from '@/workspace'

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
  <div class="q-pa-md">
    <div class="items-center no-wrap q-mb-sm row">
      <common-text
        variant="title1"
        @pointerenter="isNameHovered = true"
        @pointerleave="isNameHovered = false"
      >
        <inline-name-edit
          v-if="isNameOffered || widget.name !== ''"
          :claim="isEditingName"
          :editing="isNameOffered"
          :name="widget.name"
          @rename="(value: string) => (widget.name = value)"
          @update:editing="(value: boolean) => (isEditingName = value)"
        />
        <!-- An unnamed widget titles its dialog with the kind's own name. -->
        <template v-else>{{ getWidgetInfo(widget.type).name }}</template>
      </common-text>
      <q-space />
      <q-btn v-close-popup class="faded-hover" dense flat :icon="icons.close" round size="9px" />
    </div>
    <slot />
  </div>
</template>
