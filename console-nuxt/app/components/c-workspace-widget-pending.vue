<script lang="ts" setup>
import icons from '@/icons'
import { getWidgetInfo, type Widget } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
}>()
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center gap-1 p-4 text-center opacity-70">
    <c-icon :name="icons.workspace" size="24" />
    <c-text variant="body1">{{ getWidgetInfo(widget.type).name }}</c-text>
    <c-text variant="description">This widget kind is not part of the rewrite yet.</c-text>
  </div>
</template>
