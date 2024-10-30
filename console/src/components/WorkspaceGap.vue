<script lang="ts" setup>
import { useWorkspace } from '@/workspace'

const { row, column } = $defineProps<{
  row: number
  column?: number
  direction: 'vertical' | 'horizontal'
}>()

const workspace = useWorkspace()

let isHovered = $ref(false)

function onMouseOver() {
  isHovered = true
}

function onMouseLeave() {
  isHovered = false
}

function onMouseUp() {
  if (workspace?.drag == null) {
    return
  }

  workspace.moveWidget(workspace.drag.widget.id, row, column)
}
</script>

<template>
  <div
    :class="[
      $style.root,
      direction === 'vertical' ? $style.vertical : $style.horizontal,
      isHovered && workspace?.drag != null && $style.draggedOver,
    ]"
    @mouseleave="onMouseLeave"
    @mouseover="onMouseOver"
    @mouseup="onMouseUp"
    @pointerleave="onMouseLeave"
    @pointerover="onMouseOver"
    @pointerup="onMouseUp"
  />
</template>

<style lang="scss" module>
.root {
  background-color: grey;
  border-radius: 6px;
  z-index: 100;
  opacity: 0.5;
}

.draggedOver {
  background-color: $primary;
  opacity: 0.5;
}

.vertical {
  width: 100%;
  height: 12px;
}

.horizontal {
  width: 12px;
  height: 100%;
}
</style>
