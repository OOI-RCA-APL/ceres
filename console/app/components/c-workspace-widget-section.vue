<script lang="ts" setup>
import type { SectionWidget, WidgetRow } from '@/workspace'

const { widget, container } = defineProps<{
  widget: SectionWidget

  /** The workspace row this section sits in, whose height is the height its rows share. */
  container?: WidgetRow
}>()

// Creation and parsing both hold a section to exactly one page.
const page = $computed(() => widget.pages[0]!)
</script>

<template>
  <!-- A section has no chrome of its own, its heading is the widget header above it. The gutter is
  held whether or not a scrollbar shows, so widgets at the right edge do not jump under the hand
  arranging them as rows are added. -->
  <div class="h-full min-h-0 overflow-auto px-2 [scrollbar-gutter:stable]">
    <c-workspace-layout
      :key="page.id"
      :expand="widget.expand"
      :host="container"
      :layout="page.layout"
      :layout-id="page.id"
      :shrink="widget.shrink"
    />
  </div>
</template>
