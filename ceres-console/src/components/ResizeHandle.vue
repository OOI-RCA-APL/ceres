<template>
  <div :class="['self-root', isVertical ? 'self-vertical' : 'self-horizontal']">
    <div
      :class="[
        'self-handle',
        isVertical ? 'self-handle-vertical' : 'self-handle-horizontal',
        drag != null && 'self-handle-dragging',
      ]"
      :style="{ top: `${innerPosition.y}px`, left: `${innerPosition.x}px` }"
      @pointerdown="onPointerDown"
    />
  </div>
</template>

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

<style lang="scss" scoped>
.self-root {
  position: relative;
  background-color: rgba(0, 0, 0, 0.12);
}

.body--dark .self-root {
  background-color: rgba(255, 255, 255, 0.28);
}

.self-horizontal {
  width: 1px;
  height: 100%;
}

.self-vertical {
  height: 1px;
  width: 100%;
}

.self-handle {
  background-color: grey;
  opacity: 0;
  z-index: 1;
  transition: opacity 0.25s;
  position: absolute;
}

.self-handle:hover {
  opacity: 0.25;
}

.self-handle-dragging {
  opacity: 0.35 !important;
}

.self-handle-vertical {
  cursor: row-resize;
  height: 7px;
  width: 100%;
}

.self-handle-horizontal {
  cursor: col-resize;
  height: 100%;
  width: 7px;
}
</style>
