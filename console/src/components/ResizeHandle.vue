<script lang="ts" setup>
import { onMounted, onUnmounted } from 'vue'

import { roundTo } from '@/utilities'

const {
  direction,
  modelValue,
  min = 0,
  max,
  step,
  visibility = 'always',
} = defineProps<{
  direction: 'vertical' | 'horizontal'
  modelValue: number
  min?: number
  max?: number
  visibility?: 'hidden' | 'hover' | 'always'
  step?: number
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', modelValue: number): void
}>()

type Vector = { x: number; y: number }
type Drag = {
  start: Vector
  startModelValue: number
  end: Vector
}

function clamp(size: number) {
  if (step != null) {
    size = roundTo(size, step)
  }
  if (min != null && size < min) {
    return min
  }
  if (max != null && size > max) {
    return max
  }

  return size
}

const isVertical = $computed(() => direction == 'vertical')
const axis = isVertical ? 'y' : 'x'

let drag = $ref<Drag | null>(null)

// Where the readout sits while a size is being dragged out. Kept in viewport terms, since it is
// drawn against the window rather than in the layout the handle belongs to.
let pointer = $ref<Vector | null>(null)
const innerPositionOffset = $computed(() => (isVertical ? { x: 0, y: -3 } : { x: -3, y: 0 }))
const innerPosition = $computed(() => {
  const result = {
    x: innerPositionOffset.x,
    y: innerPositionOffset.y,
  }

  if (drag == null) {
    return result
  }

  return result
})

function onPointerDown(event: PointerEvent) {
  event.preventDefault()
  drag = {
    start: { x: event.pageX, y: event.pageY },
    startModelValue: modelValue,
    end: { x: event.pageX, y: event.pageY },
  }
  pointer = { x: event.clientX, y: event.clientY }

  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointermove', onPointerMove)
}

function onPointerMove(event: PointerEvent) {
  if (drag == null) {
    return
  }

  event.preventDefault()
  drag.end.x = Math.max(event.pageX, 0)
  drag.end.y = Math.max(event.pageY, 0)
  pointer = { x: event.clientX, y: event.clientY }
  const size = clamp(drag.startModelValue + drag.end[axis] - drag.start[axis])
  emit('update:modelValue', size)
}

function onPointerUp(event: PointerEvent) {
  if (drag == null) {
    return
  }

  event.preventDefault()
  drag.end.x = Math.max(event.pageX, 0)
  drag.end.y = Math.max(event.pageY, 0)

  const size = clamp(drag.startModelValue + drag.end[axis] - drag.start[axis])
  emit('update:modelValue', size)

  drag = null
  pointer = null
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointerup', onPointerMove)
}

onMounted(() => {
  if (modelValue !== clamp(modelValue)) {
    emit('update:modelValue', clamp(modelValue))
  }
})

onUnmounted(() => {
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointerup', onPointerMove)
})
</script>

<template>
  <div
    :class="[
      $style.root,
      $q.dark.isActive && $style.dark,
      isVertical ? $style.vertical : $style.horizontal,
      visibility === 'hidden' && $style.hidden,
      visibility === 'hover' && $style.visibleHover,
    ]"
  >
    <div :class="[$style.handleContainer, 'fit']">
      <div
        :class="[
          $style.handle,
          isVertical ? $style.handleVertical : $style.handleHorizontal,
          drag != null && $style.handleDragging,
        ]"
        :style="{ top: `${innerPosition.y}px`, left: `${innerPosition.x}px` }"
        @pointerdown="onPointerDown"
      />
    </div>
    <!-- Drawn against the window rather than in the layout, which clips its own overflow and would
    cut the readout off at the edge of the widget being sized. -->
    <teleport to="body">
      <div
        v-if="pointer != null"
        :class="[$style.readout, $q.dark.isActive && $style.readoutDark]"
        :style="{ left: `${pointer.x}px`, top: `${pointer.y}px` }"
      >
        {{ Math.round(modelValue) }}px
      </div>
    </teleport>
  </div>
</template>

<style module>
.root {
  background-color: rgba(0, 0, 0, 0.12);
}

.dark {
  background-color: rgba(255, 255, 255, 0.28);
}

.hidden {
  background-color: transparent !important;
}

.visibleHover:not(:hover) {
  background-color: transparent !important;
}

.horizontal {
  width: 1px;
  height: 100%;
}

.vertical {
  height: 1px;
  width: 100%;
}

.handleContainer {
  position: relative;
}

.handle {
  background-color: grey;
  opacity: 0;
  z-index: 10;
  transition: opacity 0.25s;
  position: absolute;
  border-radius: 4px;
}

.handle:hover {
  opacity: 0.25;
}

.handleDragging {
  opacity: 0.35 !important;
}

/* The size being dragged out, kept quiet enough to be read without being watched. Offset off the
cursor rather than under it, so the edge being placed stays in view. */
.readout {
  position: fixed;
  z-index: 6000;
  transform: translate(14px, 14px);
  padding: 1px 6px;
  border-radius: 4px;
  background-color: #ffffffe6;
  color: #00000099;
  font-size: 11px;
  line-height: 16px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  pointer-events: none;
}

.readoutDark {
  background-color: #000000b3;
  color: #ffffffa6;
}

.handleVertical {
  cursor: row-resize;
  height: 7px;
  width: 100%;
}

.handleHorizontal {
  cursor: col-resize;
  height: 100%;
  width: 7px;
}
</style>
