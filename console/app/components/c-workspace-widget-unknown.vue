<script lang="ts" setup>
import icons from '@/icons'
import type { Widget } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-1 p-4 text-center opacity-70">
    <c-icon :name="icons.help" size="24" />
    <c-text variant="body1">Unknown Widget</c-text>
    <c-text variant="description">
      This widget of type "{{ widget.type }}" is unsupported by the current Ceres version.
    </c-text>
  </div>
</template>
