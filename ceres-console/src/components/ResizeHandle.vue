<script lang="ts" setup>
import { onMounted, onUnmounted } from 'vue'

const { direction, modelValue, min, max } = defineProps<{
  direction: 'vertical' | 'horizontal'
  modelValue: number
  min?: number
  max?: number
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', modelValue: number): void
}>()

type Vector = { x: number; y: number }
type Drag = {
  start: Vector
  end: Vector
}

function clamp(size: number) {
  if (min && size < min) {
    return min
  }
  if (max && size > max) {
    return max
  }

  return size
}

const isVertical = $computed(() => direction == 'vertical')
const axis = isVertical ? 'y' : 'x'

let drag = $ref<Drag | null>(null)
const innerPositionOffset = $computed(() => (isVertical ? { x: 0, y: -3 } : { x: -3, y: 0 }))
const innerPosition = $computed(() => {
  const result = {
    x: innerPositionOffset.x,
    y: innerPositionOffset.y,
  }

  if (drag == null) {
    return result
  }

  const size = clamp(modelValue + drag.end[axis] - drag.start[axis])
  const delta = size - modelValue
  result[axis] += delta

  return result
})

function onPointerDown(event: PointerEvent) {
  event.preventDefault()
  drag = {
    start: { x: event.pageX, y: event.pageY },
    end: { x: event.pageX, y: event.pageY },
  }

  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointermove', onPointerMove)
}

function onPointerMove(event: PointerEvent) {
  if (drag == null) {
    return
  }

  event.preventDefault()
  drag.end.x = event.pageX
  drag.end.y = event.pageY
}

function onPointerUp(event: PointerEvent) {
  if (drag == null) {
    return
  }

  event.preventDefault()
  drag.end.x = event.pageX
  drag.end.y = event.pageY

  const size = clamp(modelValue + drag.end[axis] - drag.start[axis])
  emit('update:modelValue', size)

  drag = null
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
  </div>
</template>

<style module>
.root {
  background-color: rgba(0, 0, 0, 0.12);
}

.dark {
  background-color: rgba(255, 255, 255, 0.28);
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
}

.handle:hover {
  opacity: 0.25;
}

.handleDragging {
  opacity: 0.35 !important;
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
