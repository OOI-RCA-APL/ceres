<template>
  <div
    :class="[
      'self-root',
      vertical ? 'self-vertical' : 'self-horizontal',
      $q.dark.isActive && 'self-root--dark',
    ]"
  >
    <div
      :class="[
        'self-handle',
        vertical ? 'self-handle-vertical' : 'self-handle-horizontal',
        drag != null && 'self-handle-dragging',
      ]"
      :style="{ top: `${innerPosition.y}px`, left: `${innerPosition.x}px` }"
      @pointerdown="onPointerDown"
    />
  </div>
</template>

<script lang="ts" setup>
import { onUnmounted } from 'vue'

const { vertical = true } = defineProps<{
  vertical?: boolean
}>()

const emit = defineEmits<{
  (emit: 'resize', delta: number): void
}>()

type Vector = { x: number; y: number }
type Drag = {
  start: Vector
  end: Vector
}

let drag = $ref<Drag | null>(null)
const innerPositionOffset = $computed(() => (vertical ? { x: 0, y: -3 } : { x: -3, y: 0 }))
const innerPosition = $computed(() => {
  const result = {
    x: innerPositionOffset.x,
    y: innerPositionOffset.y,
  }

  if (drag == null) {
    return result
  }

  if (vertical) {
    result.y += drag.end.y - drag.start.y
  } else {
    result.x += drag.end.x - drag.start.x
  }

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

  const delta = vertical ? drag.end.y - drag.start.y : drag.end.x - drag.start.x
  emit('resize', delta)

  drag = null
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointerup', onPointerMove)
}

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

.self-root--dark {
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
