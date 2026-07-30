<script lang="ts" setup>
import { useEventListener, useIntervalFn, useMediaQuery } from '@vueuse/core'
import { QMenu } from 'quasar'
import { v7 } from 'uuid'
import { watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import WorkspaceLayout from '@/components/WorkspaceLayout.vue'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { useWidgetDrop } from '@/widget-drop'
import { layoutsWithin, CarouselSlide, CarouselWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: CarouselWidget
}>()

const workspace = useWorkspace()
const drop = useWidgetDrop()

let index = $ref(0)

// Which way the last change went, so a slide arrives from the side it would have come from. A
// carousel reaching its end and starting over is still going forwards, so this follows what was
// asked for rather than which index is larger.
let direction = $ref(1)

// Paused by hand, or for as long as someone is working in it. A slide moving on under someone
// reading it is the one thing a rotating panel must not do.
//
// What counts as working in it depends on what the machine can tell. Where there is a pointer to
// hover with, it takes the focus and the pointer both, so a carousel reached into and then left
// alone carries on by itself the moment the pointer moves away. Where there is no hovering to be
// done, the focus is the whole of the answer.
let paused = $ref(false)
let focused = $ref(false)
let hovered = $ref(false)

const canHover = useMediaQuery('(hover: hover)')

const root = $ref<HTMLElement | null>(null)

// A widget picked out on one of its slides counts as well. Pressing a widget's header takes the
// press over so it can start a drag, which means the browser never moves the focus and nothing
// here would otherwise know the carousel was being worked in at all.
const holdsSelection = $computed(
  () => workspace.selection.length > 0 && layoutsWithin([widget]).has(workspace.selectionLayout)
)

const engaged = $computed(() => {
  const reached = focused || holdsSelection

  return canHover ? reached && hovered : reached
})

// The pointer moving onto a menu this carousel opened has not left it, since the menu is drawn at
// the far end of the page while still belonging to what opened it.
function onPointerLeave(event: PointerEvent) {
  const next = event.relatedTarget as HTMLElement | null
  if (next?.closest('.q-menu, .q-dialog, .q-popup-edit') != null) {
    return
  }

  hovered = false
}

// Focus moving between two things inside the carousel never leaves it, and the focus landing
// nowhere at all is reported as no destination rather than as somewhere outside.
function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (next == null || root == null || !root.contains(next)) {
    focused = false
  }
}

// Worked out from where the press landed rather than left to the focus alone. A widget's header
// takes its own press over so that it can start a drag, and a press the page never gets to handle
// moves the focus neither onto a carousel nor off one.
//
// Overlays are exempt. A menu or a dialog opened from in here is drawn at the far end of the page
// and is still this carousel being used, so reaching into one must not let it start moving again.
useEventListener(window, 'pointerdown', (event: PointerEvent) => {
  const target = event.target as HTMLElement | null
  if (target?.closest('.q-menu, .q-dialog, .q-popup-edit') != null) {
    return
  }

  focused = root != null && target != null && root.contains(target)
})

const slide = $computed(() => widget.slides[index] ?? null)

// Also held still for as long as something is actually in hand anywhere in the workspace. A drag
// measures the layouts on screen once and aims at those measurements for the rest of it, so a slide
// moving on would take the layout being aimed at off the page.
//
// A drag that has not travelled yet does not count. Pressing any widget's header anywhere takes
// hold of it in case the press turns into a drag, and treating that as one would restart the wait
// every time a widget was so much as clicked.
const isRunning = $computed(
  () => widget.autoplay && !paused && !engaged && !drop.active && widget.slides.length > 1
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

function show(next: number, by: number = 1) {
  direction = by < 0 ? -1 : 1

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

// Turning to a slide is asking to work on it, so it becomes the layout a paste lands in and the
// one the keyboard acts on. Only when it was turned to deliberately. A carousel advancing on its
// own is nobody asking for anything, and it must not move the ground under whoever is editing.
function focusSlide() {
  if (slide != null) {
    workspace.focusLayout(slide.id)
  }
}

function step(by: number) {
  show(index + by, by)
  focusSlide()

  if (isRunning) {
    pause()
    resume()
  }
}

// The dots stand for the slides, so dragging one carries its slide with it. Driven the same way
// the workspace tab strip is, since it is the same gesture on the same kind of row.
let dots = $ref<HTMLElement[]>([])

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => dots.filter((dot) => dot != null),
  onReorder: (from, to) => {
    widget.slides = moved([...widget.slides], from, to)

    // The slide being looked at stays the slide being looked at, wherever it has just been put.
    if (index === from) {
      index = to
    } else if (index > from && index <= to) {
      index--
    } else if (index < from && index >= to) {
      index++
    }
  },
})

// Held so a dot and the slide's own menu open the same one.
const nameMenu = $ref<QMenu | null>(null)

function onDotDoubleClick(at: number, event: MouseEvent) {
  step(at - index)
  nameMenu?.show(event)
}

function onDotClick(at: number) {
  // A press that turned into a drag has already done what it was for.
  if (reorder.consumeClick()) {
    return
  }

  step(at - index)
}

// Slides are added, named and taken away on the carousel itself, since a slide is a layout and a
// layout is arranged by working on it rather than by describing it somewhere else. A new one is
// shown at once, so the next thing done lands on the slide that was just asked for.
function addSlide() {
  const slide: CarouselSlide = { id: v7(), name: '', layout: [] }
  widget.slides = [...widget.slides, slide]
  index = widget.slides.length - 1
  workspace.focusLayout(slide.id)
}

function deleteSlide() {
  if (slide == null) {
    return
  }

  const removing = slide
  widget.slides = widget.slides.filter((current) => current !== removing)
  show(index)
}

function moveSlide(by: number) {
  const to = index + by
  if (slide == null || to < 0 || to >= widget.slides.length) {
    return
  }

  const slides = [...widget.slides]
  slides.splice(index, 1)
  slides.splice(to, 0, slide)
  widget.slides = slides
  index = to
}
</script>

<template>
  <!-- Focusable itself, so that pressing anywhere on it counts as reaching into it even where
  there is nothing of its own to focus. Out of the tab order, since the things inside it are the
  things worth tabbing to and reaching any of them focuses this all the same. -->
  <div
    ref="root"
    :class="[$style.root, 'column', 'full-height', 'no-wrap']"
    tabindex="-1"
    @focusin="focused = true"
    @focusout="onFocusOut"
    @pointerenter="hovered = true"
    @pointerleave="onPointerLeave"
  >
    <div v-if="slide == null" :class="[$style.empty, 'col', 'column', 'flex-center']">
      <common-text variant="description">A carousel shows one slide at a time.</common-text>
      <q-btn
        class="q-mt-sm"
        color="primary"
        dense
        flat
        :icon="icons.add"
        label="Add Slide"
        no-caps
        size="sm"
        @click="addSlide"
      />
    </div>
    <!-- A slide is a workspace in miniature, arranged through the same editor the workspace itself
    is drawn by, so everything that can be done to a layout can be done to one. -->
    <template v-else>
      <!-- Slides travel sideways, arriving from the side the carousel is heading towards and
      leaving to the other. Both are on screen for as long as it takes, which is what makes turning
      to the next one read as one thing giving way to another rather than as a swap. -->
      <div :class="[$style.viewport, 'col']">
        <transition
          :enter-active-class="$style.travelling"
          :enter-from-class="direction > 0 ? $style.offRight : $style.offLeft"
          :leave-active-class="$style.travelling"
          :leave-to-class="direction > 0 ? $style.offLeft : $style.offRight"
        >
          <div :key="slide.id" :class="[$style.slide, 'overflow-auto', 'q-px-sm']">
            <workspace-layout :layout="slide.layout" :layout-id="slide.id" />
          </div>
        </transition>
      </div>
    </template>
    <!-- Stepping through a carousel is its own band under the slide, dressed the way a widget's
    header is, so it reads as the carousel's own chrome rather than as something laid on the slide.
    Held back until there is a slide, since the empty state asks for one itself. -->
    <template v-if="slide != null">
      <q-separator />
      <!-- Laid out in three, with the outer two the same width whatever they hold, so the dots sit
      at the middle of the carousel rather than at the middle of whatever room the buttons left. -->
      <div :class="[$style.controls, 'items-center', 'q-px-sm']">
        <div />
        <div :class="[$style.steps, 'items-center', 'justify-center', 'no-wrap', 'row']">
          <!-- Only worth steering when there is somewhere to steer to. -->
          <template v-if="widget.slides.length > 1">
            <q-btn dense flat :icon="icons.menuLeft" round size="10px" @click="step(-1)">
              <q-tooltip class="bg-primary">Previous</q-tooltip>
            </q-btn>
            <button
              v-for="(current, at) in widget.slides"
              :key="current.id"
              ref="dots"
              aria-label="Show slide"
              :class="[
                $style.dot,
                at === index && $style.dotCurrent,
                reorder.isSwapping && $style.dotSwapping,
                reorder.isHeld(at) && $style.dotHeld,
                reorder.isGrabbed(at) && $style.dotGrabbed,
              ]"
              :style="reorder.styleFor(at)"
              type="button"
              v-bind="reorder.handlers(at)"
              @click="onDotClick(at)"
              @dblclick="onDotDoubleClick(at, $event)"
            >
              <!-- How long is left of this slide, drawn as a ring closing around its dot. Keyed on
            the slide so the sweep starts over each time one is turned to, which is also when the
            wait itself restarts. Gone whenever the carousel is not advancing, since the wait is
            reset rather than held wherever it had got to, and a part-drawn ring would claim
            otherwise. -->
              <svg
                v-if="isRunning && at === index"
                :key="index"
                :class="$style.sweep"
                viewBox="0 0 24 24"
              >
                <!-- Timed on the circle rather than on the box around it, since the circle is what
              carries the animation and a duration set anywhere else never reaches it. -->
                <circle
                  cx="12"
                  cy="12"
                  fill="none"
                  r="10"
                  stroke="currentColor"
                  stroke-width="1.75"
                  :style="{ animationDuration: `${Math.max(widget.interval, 1)}s` }"
                />
              </svg>
              <q-tooltip v-if="!reorder.isDragging" class="bg-primary">{{
                current.name !== '' ? current.name : `Slide ${at + 1}`
              }}</q-tooltip>
            </button>
            <q-btn dense flat :icon="icons.menuRight" round size="10px" @click="step(1)">
              <q-tooltip class="bg-primary">Next</q-tooltip>
            </q-btn>
          </template>
          <!-- A slide is named on its dot, which is the thing that stands for it everywhere else.
          Opened deliberately, by double-clicking a dot or from the slide's own menu, since a single
          press on a dot is what turns to that slide. -->
          <q-menu ref="nameMenu" no-parent-event touch-position>
            <q-input
              autofocus
              :class="$style.nameField"
              dense
              label="Slide Title"
              :model-value="slide?.name ?? ''"
              outlined
              @keyup.enter="nameMenu?.hide()"
              @update:model-value="(value) => slide != null && (slide.name = String(value ?? ''))"
            />
          </q-menu>
        </div>
        <div :class="[$style.actions, 'items-center', 'no-wrap', 'row']">
          <q-btn
            v-if="widget.autoplay && widget.slides.length > 1"
            dense
            flat
            :icon="paused ? icons.start : icons.pause"
            round
            size="10px"
            @click="paused = !paused"
          >
            <q-tooltip class="bg-primary">{{ paused ? 'Resume' : 'Pause' }}</q-tooltip>
          </q-btn>
          <q-btn dense flat :icon="icons.add" round size="10px" @click="addSlide">
            <q-tooltip class="bg-primary">Add Slide</q-tooltip>
          </q-btn>
          <!-- The slide being shown is the one these act on, since it is the one being looked
          at. -->
          <q-btn dense flat :icon="icons.more" round size="10px">
            <q-menu>
              <q-list bordered dense>
                <q-item v-close-popup clickable dense @click="nameMenu?.show()">
                  <q-item-section avatar>
                    <q-icon :name="icons.rename" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Set Title</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-close-popup clickable dense :disable="index === 0" @click="moveSlide(-1)">
                  <q-item-section avatar>
                    <q-icon :name="icons.menuLeft" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Move Slide Earlier</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  dense
                  :disable="index === widget.slides.length - 1"
                  @click="moveSlide(1)"
                >
                  <q-item-section avatar>
                    <q-icon :name="icons.menuRight" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Move Slide Later</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense @click="deleteSlide">
                  <q-item-section avatar>
                    <q-icon :name="icons.delete" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Delete Slide</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
        </div>
      </div>
    </template>
  </div>
</template>

<style lang="scss" module>
@use 'sass:color';

// Takes the focus so that reaching into it can be told from passing over it, and shows nothing for
// it. The focus is only being watched here, not being offered as somewhere to type.
.root:focus,
.root:focus-visible {
  outline: none;
}

.empty {
  opacity: 0.7;
}

// Takes the room left over rather than asking for the room its contents want, so the band under it
// keeps its place however much a slide happens to hold. What a slide travels through, which is why
// nothing is drawn outside it.
.viewport {
  position: relative;
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

// Laid over the viewport rather than in it, so the slide arriving and the slide leaving pass each
// other rather than standing one after the other.
.slide {
  position: absolute;
  inset: 0;

  // Room for the scrollbar whether or not one is showing. A slide is as tall as its rows say, so
  // one arrives and goes as rows are added and resized, and content that reflowed each time it did
  // would leave the widgets at the right edge jumping under the hand arranging them.
  scrollbar-gutter: stable;
}

// Long enough to be followed across the width of a widget, and short enough not to be waited on.
.travelling {
  transition: transform 260ms cubic-bezier(0.2, 0, 0, 1);
}

.offRight {
  transform: translateX(100%);
}

.offLeft {
  transform: translateX(-100%);
}

// Three columns with the outer two forced to the same width, which is what holds the middle one at
// the centre of the band however many buttons sit at the end of it.
.controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  padding-top: 3px;
  padding-bottom: 3px;
}

.steps {
  gap: 6px;
}

// Wide enough to read a slide's title back without the popup sizing itself to what is typed.
.nameField {
  margin: 8px;
  width: 200px;
}

.actions {
  gap: 6px;
  justify-self: end;
}

:global(.light) .controls {
  background-color: color.adjust(white, $lightness: -1%);
}

// Small enough to sit under a slide without competing with it, and large enough to aim at. Drawn
// in its own right rather than as a faded shade of whatever text colour it inherits, which left it
// too near the band behind it to make out.
.dot {
  position: relative;
  width: 9px;
  height: 9px;
  padding: 0;
  border: none;
  border-radius: 50%;
  margin: 0 1.5px;
  cursor: pointer;
  transition: background-color 160ms ease-out, transform 160ms ease;
  touch-action: none;
}

:global(.dark) .dot {
  background-color: #ffffff8c;
}

:global(.dark) .dot:hover {
  background-color: #ffffffd9;
}

:global(.light) .dot {
  background-color: #00000073;
}

:global(.light) .dot:hover {
  background-color: #000000b3;
}

// Qualified the same way, or the theme rules above would beat it on specificity.
:global(.dark) .dotCurrent,
:global(.light) .dotCurrent {
  background-color: $primary;
}

.dotHeld {
  z-index: 2;
}

// The held dot tracks the pointer directly, so it must not smooth its own movement. It regains the
// transition once released, which is what animates it into the gap.
.dotGrabbed {
  cursor: grabbing;
  transition: background-color 160ms ease-out;
}

.dotSwapping {
  transition: none;
}

// The ring closes clockwise from the top, drawn as a circle whose dash is drawn back in over the
// wait. An outline rather than a fill, so the dot underneath still says which slide is showing.
@keyframes sweep {
  from {
    stroke-dashoffset: 62.83;
  }

  to {
    stroke-dashoffset: 0;
  }
}

.sweep {
  position: absolute;
  inset: -5px;
  color: $primary;
  pointer-events: none;
  overflow: visible;
}

.sweep circle {
  stroke-dasharray: 62.83;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  animation-name: sweep;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
</style>
