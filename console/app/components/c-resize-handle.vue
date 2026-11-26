<script lang="ts" setup>
import { onMounted, onUnmounted } from 'vue'

import { roundTo } from '@/utilities'

const {
  direction,
  modelValue,
  measure,
  min = 0,
  max,
  step,
  visibility = 'always',
  readout = true,
  label,
} = defineProps<{
  direction: 'vertical' | 'horizontal'

  /** The size in pixels, or null while what is sized takes its size from its contents. */
  modelValue: number | null

  /** Read the size what is sized has on screen, where a drag starts from while `modelValue` is
  null. */
  measure?: () => number

  min?: number
  max?: number
  visibility?: 'hidden' | 'hover' | 'always'
  step?: number

  /** Whether to trail the size in pixels beside the cursor.

  Turned off where what is being sized is better said some other way than in pixels, and the caller
  says it itself while `dragging` is true.
  */
  readout?: boolean

  /** What the grip sizes, for a screen reader. */
  label?: string
}>()

const emit = defineEmits<{
  (emit: 'update:modelValue', modelValue: number): void
  /** Whether a size is being dragged out right now, for a caller that draws its own readout. */
  (emit: 'update:dragging', dragging: boolean): void
  /** A double click, asking to return to sizing from the contents. */
  (emit: 'reset'): void
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
  if (size < min) {
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

function onPointerDown(event: PointerEvent) {
  event.preventDefault()
  drag = {
    start: { x: event.pageX, y: event.pageY },
    startModelValue: modelValue ?? measure?.() ?? 0,
    end: { x: event.pageX, y: event.pageY },
  }
  pointer = { x: event.clientX, y: event.clientY }
  emit('update:dragging', true)

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

  // A click without movement sizes nothing, so a row sized to its contents stays so and a
  // double click can reset it.
  if (drag.end[axis] !== drag.start[axis]) {
    emit('update:modelValue', clamp(drag.startModelValue + drag.end[axis] - drag.start[axis]))
  }

  drag = null
  pointer = null
  emit('update:dragging', false)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointermove', onPointerMove)
}

onMounted(() => {
  if (modelValue != null && modelValue !== clamp(modelValue)) {
    emit('update:modelValue', clamp(modelValue))
  }
})

onUnmounted(() => {
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointermove', onPointerMove)
})
</script>

<template>
  <div
    class="bg-[#0000001f] dark:bg-[#ffffff47]"
    :class="[
      isVertical ? 'h-px w-full' : 'h-full w-px',
      visibility === 'hidden' && 'bg-transparent!',
      visibility === 'hover' && 'not-hover:bg-transparent!',
    ]"
  >
    <div class="relative h-full w-full">
      <div
        :aria-label="label"
        :aria-orientation="isVertical ? 'horizontal' : 'vertical'"
        :class="[
          'absolute z-10 rounded bg-[grey] opacity-0 transition-opacity duration-250',
          'hover:opacity-25',
          isVertical ? 'h-[7px] w-full cursor-row-resize' : 'h-full w-[7px] cursor-col-resize',
          drag != null && 'opacity-35!',
        ]"
        role="separator"
        :style="isVertical ? { top: '-3px' } : { left: '-3px' }"
        @dblclick="emit('reset')"
        @pointerdown="onPointerDown"
      />
    </div>
    <!-- Drawn against the window rather than in the layout, which clips its own overflow and would
    cut the readout off at the edge of the widget being sized. -->
    <teleport to="body">
      <div
        v-if="readout && pointer != null && modelValue != null"
        :class="[
          'pointer-events-none fixed z-[6000] translate-x-3.5 translate-y-3.5 rounded px-1.5',
          'py-px text-[11px] leading-4 whitespace-nowrap tabular-nums',
          'bg-[#ffffffe6] text-[#00000099] dark:bg-[#000000b3] dark:text-[#ffffffa6]',
        ]"
        :style="{ left: `${pointer.x}px`, top: `${pointer.y}px` }"
      >
        {{ Math.round(modelValue) }}px
      </div>
    </teleport>
  </div>
</template>
