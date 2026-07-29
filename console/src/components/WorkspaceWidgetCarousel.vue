<script lang="ts" setup>
import { useIntervalFn } from '@vueuse/core'
import { watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import WorkspaceLayout from '@/components/WorkspaceLayout.vue'
import icons from '@/icons'
import { CarouselWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: CarouselWidget
}>()

const workspace = useWorkspace()

let index = $ref(0)

// Paused by hand, or while the pointer is over it. A slide moving on under someone reading it is
// the one thing a rotating panel must not do.
let paused = $ref(false)
let hovered = $ref(false)

const slide = $computed(() => widget.slides[index] ?? null)

// Also held still for as long as anything is in hand anywhere in the workspace. A drag measures
// the layouts on screen once and aims at those measurements for the rest of it, so a slide moving
// on would take the layout being aimed at off the page.
const isRunning = $computed(
  () => widget.autoplay && !paused && !hovered && workspace.drag == null && widget.slides.length > 1
)

// Slides can be taken away from under it, so the position is kept inside what is actually there.
watch(
  () => widget.slides.length,
  (length) => {
    if (index >= length) {
      index = 0
    }
  }
)

function show(next: number) {
  const length = widget.slides.length
  if (length === 0) {
    index = 0
    return
  }

  index = ((next % length) + length) % length
}

// Stepping through by hand restarts the wait, so a slide reached deliberately is shown for as long
// as any other rather than for whatever was left of the one before it.
const { pause, resume } = useIntervalFn(
  () => show(index + 1),
  () => Math.max(widget.interval, 1) * 1000
)

watch(
  () => isRunning,
  (running) => (running ? resume() : pause()),
  { immediate: true }
)

function step(by: number) {
  show(index + by)
  if (isRunning) {
    pause()
    resume()
  }
}
</script>

<template>
  <div
    :class="[$style.root, 'column', 'full-height', 'no-wrap']"
    @pointerenter="hovered = true"
    @pointerleave="hovered = false"
  >
    <div v-if="slide == null" :class="[$style.empty, 'col', 'flex', 'flex-center']">
      <common-text variant="description">
        No slides yet. Add some from this widget's settings.
      </common-text>
    </div>
    <template v-else>
      <!-- A slide is a workspace in miniature, arranged through the same editor the workspace
      itself is drawn by, so everything that can be done to a layout can be done to one. -->
      <div :class="[$style.slide, 'overflow-auto', 'q-px-sm']">
        <workspace-layout :key="slide.id" :layout="slide.layout" :layout-id="slide.id" />
      </div>
      <!-- Only worth steering when there is somewhere to steer to. -->
      <div
        v-if="widget.slides.length > 1"
        :class="[$style.controls, 'items-center', 'justify-center', 'no-wrap', 'row']"
      >
        <q-btn dense flat :icon="icons.menuLeft" round size="9px" @click="step(-1)">
          <q-tooltip class="bg-primary">Previous</q-tooltip>
        </q-btn>
        <button
          v-for="(current, at) in widget.slides"
          :key="current.id"
          aria-label="Show slide"
          :class="[$style.dot, at === index && $style.dotCurrent]"
          type="button"
          @click="step(at - index)"
        >
          <q-tooltip v-if="current.name !== ''" class="bg-primary">{{ current.name }}</q-tooltip>
        </button>
        <q-btn dense flat :icon="icons.menuRight" round size="9px" @click="step(1)">
          <q-tooltip class="bg-primary">Next</q-tooltip>
        </q-btn>
        <q-btn
          v-if="widget.autoplay"
          dense
          flat
          :icon="paused ? icons.start : icons.pause"
          round
          size="9px"
          @click="paused = !paused"
        >
          <q-tooltip class="bg-primary">{{ paused ? 'Resume' : 'Pause' }}</q-tooltip>
        </q-btn>
      </div>
    </template>
  </div>
</template>

<style lang="scss" module>
.root {
  gap: 4px;
}

.empty {
  opacity: 0.7;
}

// Takes the room left over rather than asking for the room its contents want, so the controls
// under it keep their place however much a slide happens to hold.
.slide {
  flex: 1 1 0;
  min-height: 0;
}

.controls {
  gap: 5px;
  padding-bottom: 2px;
}

// Small enough to sit under a slide without competing with it, and large enough to aim at.
.dot {
  width: 7px;
  height: 7px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background-color: currentColor;
  opacity: 0.3;
  cursor: pointer;
  transition: opacity 160ms ease-out;
}

.dot:hover {
  opacity: 0.6;
}

.dotCurrent {
  background-color: $primary;
  opacity: 1;
}
</style>
