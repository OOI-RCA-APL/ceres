<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { useEventListener, useIntervalFn, useMediaQuery } from '@vueuse/core'
import { v7 } from 'uuid'
import { nextTick, watch } from 'vue'

import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { moved, usePointerReorder } from '@/reorder'
import { useWidgetDrop } from '@/widget-drop'
import { convertedPagesWidget, layoutsWithin, useWorkspace } from '@/workspace'
import type { CarouselSlide, CarouselWidget, WidgetRow } from '@/workspace'

const { widget, container } = defineProps<{
  widget: CarouselWidget

  /** The workspace row this carousel sits in, whose height is the height its slides get. */
  container?: WidgetRow
}>()

const workspace = useWorkspace()
const drop = useWidgetDrop()

let index = $ref(0)

// Which way the last change went so a slide arrives from the side it would have come from. A
// carousel reaching its end and starting over is still going forwards so this follows what was
// asked for rather than which index is larger.
let direction = $ref(1)

// Paused by hand, or for as long as someone is working in it, so a slide never moves on under
// someone reading it. With a pointer available, resuming needs the focus and the pointer both
// gone so a carousel left alone continues the moment the pointer moves away. On touch devices,
// focus alone decides.
let paused = $ref(false)
let focused = $ref(false)
let hovered = $ref(false)

const canHover = useMediaQuery('(hover: hover)')

const rootElement = $ref<HTMLElement | null>(null)

// A widget picked out on one of its slides counts as well. Pressing a widget's header takes the
// press over so it can start a drag, which means the browser never moves the focus and nothing
// here would otherwise know the carousel was being worked in at all.
const holdsSelection = $computed(
  () => workspace.selection.length > 0 && layoutsWithin([widget]).has(workspace.selectionLayout),
)

const engaged = $computed(() => {
  const reached = focused || holdsSelection

  return canHover.value ? reached && hovered : reached
})

// An overlay this carousel opened is drawn at the far end of the page while still belonging to
// what opened it, so reaching into one must not let the carousel start moving again.
const overlaySelector = '[role="menu"], [role="dialog"], [role="tooltip"]'

function onPointerLeave(event: PointerEvent) {
  const next = event.relatedTarget as HTMLElement | null
  if (next?.closest(overlaySelector) != null) {
    return
  }

  hovered = false
}

// Focus moving between two things inside the carousel never leaves it, and the focus landing
// nowhere at all is reported as no destination rather than as somewhere outside.
function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (next == null || rootElement == null || !rootElement.contains(next)) {
    focused = false
  }
}

// Worked out from where the press landed rather than left to the focus alone. A widget's header
// takes its own press over so that it can start a drag, and a press the page never gets to handle
// moves the focus neither onto a carousel nor off one.
useEventListener(window, 'pointerdown', (event: PointerEvent) => {
  const target = event.target as HTMLElement | null
  if (target?.closest(overlaySelector) != null) {
    return
  }

  focused = rootElement != null && target != null && rootElement.contains(target)
})

const slide = $computed(() => widget.slides[index] ?? null)

// Which slide is open is this browser's own place in the workspace rather than part of it so it
// survives a reload here and goes nowhere else. Held as the slide's ID rather than its position
// so slides reordered or deleted from another seat cannot restore somebody else's slide.
const persisted = usePersisted({
  schema: (zod) => zod.object({ slide: zod.string().nullable().catch(null).default(null) }),
  methods: [{ type: 'local-storage', key: ['widget-slide', widget.id] }],
})

const remembered = widget.slides.findIndex((current) => current.id === persisted.slide)
if (remembered >= 0) {
  // The position alone, without focusing the slide's layout, which would steal the workspace's
  // focused layout on every reload for every carousel on it.
  index = remembered
}

watch(
  () => slide?.id ?? null,
  (id) => {
    persisted.slide = id
  },
)

// A slide is as tall as the carousel however little is on it so the height left at the bottom
// goes somewhere. The last row is the default, being where a table or a chart wants the room.
const expandOptions = [
  { label: 'Last Widget Row', value: 'last' },
  { label: 'First Widget Row', value: 'first' },
  { label: 'All Widget Rows', value: 'even' },
  { label: "Don't Fill", value: 'none' },
]

// Also held still for as long as something is actually in hand anywhere in the workspace. A drag
// measures the layouts on screen once and aims at those measurements for the rest of it so a slide
// moving on would take the layout being aimed at off the page.
const isRunning = $computed(
  () => widget.autoplay && !paused && !engaged && !drop.active && widget.slides.length > 1,
)

// Slides can be taken away from under it so the position is kept inside what is actually there.
watch(
  () => widget.slides.length,
  (length) => {
    if (index >= length) {
      index = 0
    }
  },
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

// Stepping through by hand restarts the wait so a slide reached deliberately is shown for as long
// as any other rather than for whatever was left of the one before it.
const { pause, resume } = useIntervalFn(
  () => show(index + 1),
  () => Math.max(widget.interval, 1) * 1000,
)

watch(
  () => isRunning,
  (running) => (running ? resume() : pause()),
  { immediate: true },
)

// Turning to a slide is asking to work on it so it becomes the layout a paste lands in and the
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

// The dots stand for the slides so dragging one carries its slide with it. Driven the same way
// the workspace tab strip is since it is the same gesture on the same kind of row.
let bandElement = $ref<HTMLElement | null>(null)

const dotElements = () => [...(bandElement?.querySelectorAll<HTMLElement>('[data-dot]') ?? [])]

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: dotElements,
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

// A slide is named on the dot that stands for it. The popup holding the name is the field for it
// as well so reading a slide's name and changing it are the same place rather than two.
let namingDot = $ref<number | null>(null)

/** Whether the name takes the caret as it opens. A rename asked for from the menu is meant to be
typed into at once, while a dot press is only showing the name and waits to be clicked into. */
let isClaimingName = $ref(false)

function onDotClick(at: number) {
  // A press that turned into a drag has already done what it was for.
  if (reorder.consumeClick()) {
    return
  }

  // Pressing the dot of the slide already shown reads out its name, since turning to it would
  // change nothing.
  if (at === index) {
    isClaimingName = false
    namingDot = at
    return
  }

  step(at - index)
}

function startNaming() {
  isClaimingName = true
  namingDot = index
}

// Slides are added, named and taken away on the carousel itself since a slide is a layout and a
// layout is arranged by working on it rather than by describing it somewhere else. A new one is
// shown at once so the next thing done lands on the slide that was just asked for.
function addSlide() {
  const added: CarouselSlide = { id: v7(), name: '', layout: [] }
  widget.slides = [...widget.slides, added]
  index = widget.slides.length - 1
  workspace.focusLayout(added.id)
}

function deleteSlide() {
  // Never down to none. A carousel holding no slides has no layout so nothing could be dragged
  // onto it or pasted into it, and taking the last slide away would leave it with no way back.
  if (slide == null || widget.slides.length <= 1) {
    return
  }

  const removing = slide
  widget.slides = widget.slides.filter((current) => current !== removing)
  show(index)
}

/** Turn this carousel into a tab strip holding the same pages, in the same place.

The pages travel as they are, under the names they already had, so what is on them and what a drop
into any of them means are untouched. Only how they are reached changes.
*/
function convertToTabs() {
  const tabs = convertedPagesWidget(widget)
  if (tabs != null) {
    workspace.replaceWidget(widget.id, tabs)
  }
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

// A widget carried over the band is being brought to a slide rather than to the one on show, so
// the carousel turns to whichever dot it is held over and the drop lands there. Held over for a
// moment first since crossing the band on the way somewhere else is not a change of mind.
const dwellBeforeTurning = 280

let turning: ReturnType<typeof setTimeout> | null = null

// What the wait is for so travelling across a dot does not start it over on every step of the
// pointer. `undefined` is nothing waited for, and null is the band's own room around the dots.
let awaited: number | null | undefined = undefined

function stopTurning() {
  if (turning != null) {
    clearTimeout(turning)
    turning = null
  }

  awaited = undefined
}

// A slide offered rather than made. Nothing but a drawing so a workspace saved mid-drag holds no
// trace of it. It becomes a slide the moment a widget is let go of on it, and not before.
let ghost = $ref(false)

function onBandPointerLeave() {
  stopTurning()
  ghost = false
}

/** Whichever dot the pointer is over, or null for the band's own room around them. */
function onBandPointerOver(event: PointerEvent) {
  if (workspace.drag == null) {
    return
  }

  const over = (event.target as HTMLElement | null)?.closest('[data-dot]') ?? null
  const at = over == null ? -1 : dotElements().indexOf(over as HTMLElement)
  turnWhileDragging(at >= 0 ? at : null)
}

function turnWhileDragging(at: number | null) {
  if (awaited === at) {
    return
  }

  stopTurning()
  awaited = at

  if (workspace.drag == null) {
    return
  }

  turning = setTimeout(() => {
    turning = null
    awaited = undefined

    // A slide of its own for a widget dropped into the band's spare room since that room is the
    // one place a carousel can be added to by carrying something to it.
    if (at == null) {
      ghost = true
      return
    }

    show(at, at - index)
    focusSlide()

    // The slide it turned to was never on screen when the drag was measured, and it takes its
    // travel to arrive so it is measured once it has come to rest.
    setTimeout(() => drop.remeasure(), 300)
  }, dwellBeforeTurning)
}

/** Take the widget in hand onto a slide of its own, made here and now for it to land on.

Runs on the ghost's own `pointerup`, which arrives before the drop system's window-level release,
so the slide exists and holds the widget by the time release runs.
*/
function onGhostDrop() {
  const drag = workspace.drag
  if (drag == null || !drop.active) {
    return
  }

  const opened: CarouselSlide = { id: v7(), name: '', layout: [] }
  widget.slides = [...widget.slides, opened]
  workspace.moveWidgets(
    drag.widgets.map((held) => held.id),
    { layout: opened.id, row: 0, column: null },
  )
  show(widget.slides.length - 1)
  focusSlide()
  ghost = false
}

// An offer not taken goes away with the drag that asked for it.
watch(
  () => workspace.drag != null,
  (dragging) => {
    if (!dragging) {
      ghost = false
    }
  },
)

// The slide being shown is the one these act on since it is the one being looked at. How the
// carousel runs, rather than what is on any one slide, sits below the rule at the end.
const menuItems = $computed<DropdownMenuItem[][]>(() => [
  [
    {
      label: 'Rename Slide',
      icon: icons.rename,
      // Opened once the menu has gone, since the popup carrying the field reads the menu handing
      // focus back to its own trigger as a click away.
      onSelect: () => setTimeout(startNaming, 150),
    },
    {
      label: 'Move Slide Earlier',
      icon: icons.menuLeft,
      disabled: index === 0,
      onSelect: () => moveSlide(-1),
    },
    {
      label: 'Move Slide Later',
      icon: icons.menuRight,
      disabled: index === widget.slides.length - 1,
      onSelect: () => moveSlide(1),
    },
  ],
  [
    {
      label: 'Delete Slide',
      icon: icons.delete,
      disabled: widget.slides.length <= 1,
      onSelect: deleteSlide,
    },
  ],
  [{ label: 'Convert To Tabs', icon: icons.tab, onSelect: convertToTabs }],
  [
    {
      label: 'Autoplay',
      type: 'checkbox',
      checked: widget.autoplay,
      onUpdateChecked: (value: boolean) => (widget.autoplay = value),
    },
    ...(widget.expand !== 'none'
      ? [
          {
            label: 'Shrink',
            type: 'checkbox' as const,
            checked: widget.shrink,
            onUpdateChecked: (value: boolean) => (widget.shrink = value),
          },
        ]
      : []),
    {
      label: 'Fill Slide Height',
      children: expandOptions.map((option) => ({
        label: option.label,
        type: 'checkbox' as const,
        checked: widget.expand === option.value,
        onUpdateChecked: () => (widget.expand = option.value as CarouselWidget['expand']),
      })),
    },
  ],
])

// The field is already standing when the popup arrives, so it never sees the change that would
// otherwise have it take the caret for itself.
async function focusSlideName() {
  if (!isClaimingName) {
    return
  }

  await nextTick()
  document.querySelector<HTMLInputElement>('[data-slide-name] input')?.focus()
}
</script>

<template>
  <!-- Focusable itself so that pressing anywhere on it counts as reaching into it even where
  there is nothing of its own to focus. Out of the tab order since the things inside it are the
  things worth tabbing to and reaching any of them focuses this all the same. -->
  <div
    ref="rootElement"
    class="flex h-full flex-col flex-nowrap outline-none"
    tabindex="-1"
    @focusin="focused = true"
    @focusout="onFocusOut"
    @pointerenter="hovered = true"
    @pointerleave="onPointerLeave"
  >
    <!-- The same button a layout with nothing on it offers so adding the first slide is the thing
    it already is everywhere else rather than something else to read. -->
    <div v-if="slide == null" class="flex min-h-[60px] flex-1 flex-col items-center justify-center">
      <c-tooltip text="Add Slide">
        <c-button
          aria-label="Add Slide"
          class="rounded-full"
          color="primary"
          :icon="icons.add"
          size="xs"
          @click="addSlide"
        />
      </c-tooltip>
    </div>
    <!-- Slides travel sideways, arriving from the side the carousel is heading towards and
    leaving to the other. Both stay on screen during the turn so it reads as one slide giving
    way to another. -->
    <div v-else class="relative min-h-0 flex-1 overflow-hidden">
      <transition
        :enter-active-class="$style.travelling"
        :enter-from-class="direction > 0 ? $style.offRight : $style.offLeft"
        :leave-active-class="$style.travelling"
        :leave-to-class="direction > 0 ? $style.offLeft : $style.offRight"
      >
        <!-- A slide is a workspace in miniature, arranged through the same editor the workspace
        itself is drawn by so everything that can be done to a layout can be done to one. -->
        <!-- The gutter is held whether or not a scrollbar shows, since a slide is as tall as its
        rows say and content reflowing each time one arrives would leave the widgets at the right
        edge jumping under the hand arranging them. -->
        <div :key="slide.id" class="absolute inset-0 overflow-auto px-2 [scrollbar-gutter:stable]">
          <c-workspace-layout
            :expand="widget.expand"
            :host="container"
            :layout="slide.layout"
            :layout-id="slide.id"
            :shrink="widget.shrink"
          />
        </div>
      </transition>
    </div>
    <!-- Stepping through a carousel is its own band under the slide, dressed the way a widget's
    header is so it reads as the carousel's own chrome rather than as something laid on the slide.
    Laid out in three, with the outer two the same width whatever they hold, so the dots sit at the
    middle of the carousel rather than at the middle of whatever room the buttons left. -->
    <div
      v-if="slide != null"
      ref="bandElement"
      :class="[
        'border-default grid items-center border-t px-2 py-[3px]',
        'grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]',
      ]"
      data-no-drop
      @pointerleave="onBandPointerLeave"
      @pointerover="onBandPointerOver"
    >
      <div />
      <div class="flex flex-nowrap items-center justify-center gap-1.5">
        <!-- Only worth steering when there is somewhere to steer to. -->
        <template v-if="widget.slides.length > 1">
          <c-tooltip text="Previous">
            <c-button :icon="icons.menuLeft" size="xs" variant="link" @click="step(-1)" />
          </c-tooltip>
          <!-- The name, and the field for it, are the same thing, opened from the dot of the
          slide already showing since turning to it would change nothing. -->
          <!-- A popup takes the caret as it opens, which would put a pressed dot straight into
          renaming the slide it only meant to name. Held off unless the rename was asked for. -->
          <c-popover
            v-for="(current, at) in widget.slides"
            :key="current.id"
            :content="{
              onOpenAutoFocus: (event: Event) => !isClaimingName && event.preventDefault(),
            }"
            :open="namingDot === at && !reorder.isDragging && workspace.drag == null"
            :ui="{ content: 'p-1' }"
            @after:enter="focusSlideName()"
            @update:open="(open: boolean) => (namingDot = open ? at : null)"
          >
            <button
              aria-label="Show slide"
              :class="[
                $style.dot,
                at === index && $style.dotCurrent,
                reorder.isSwapping && $style.dotSwapping,
                reorder.isHeld(at) && $style.dotHeld,
                reorder.isGrabbed(at) && $style.dotGrabbed,
              ]"
              data-dot
              :data-drop-layout="workspace.drag != null ? current.id : undefined"
              :style="reorder.styleFor(at)"
              type="button"
              v-on="reorder.handlers(at)"
              @click="onDotClick(at)"
            >
              <!-- How long is left of this slide, drawn as a ring closing around its dot. Keyed on
              the slide so the sweep starts over each time one is turned to, which is also when the
              wait itself restarts. Gone whenever the carousel is not advancing since the wait is
              reset rather than held wherever it had got to. -->
              <svg
                v-if="isRunning && at === index"
                :key="index"
                :class="$style.sweep"
                viewBox="0 0 24 24"
              >
                <!-- Timed on the circle rather than on the box around it since the circle is what
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
            </button>
            <template #content>
              <c-text class="block whitespace-nowrap" data-slide-name variant="th">
                <c-inline-name-edit
                  :claim="isClaimingName"
                  editing
                  :name="current.name !== '' ? current.name : `Slide ${at + 1}`"
                  @rename="(value: string) => (current.name = value)"
                  @update:editing="(editing: boolean) => (namingDot = editing ? at : null)"
                />
              </c-text>
            </template>
          </c-popover>
          <c-tooltip text="Next">
            <c-button :icon="icons.menuRight" size="xs" variant="link" @click="step(1)" />
          </c-tooltip>
        </template>
        <!-- The slide a drop into the band would make, drawn rather than made. Its own pointerup
        is what makes it real so letting go anywhere else leaves no trace of it. -->
        <button
          v-if="ghost"
          aria-label="New Slide"
          :class="$style.ghostDot"
          type="button"
          @pointerup="onGhostDrop"
        />
      </div>
      <div class="flex flex-nowrap items-center justify-self-end">
        <c-tooltip
          v-if="widget.autoplay && widget.slides.length > 1"
          :text="paused ? 'Resume' : 'Pause'"
        >
          <c-button
            :icon="paused ? icons.start : icons.pause"
            size="xs"
            variant="link"
            @click="paused = !paused"
          />
        </c-tooltip>
        <c-tooltip text="Add Slide">
          <c-button :icon="icons.add" size="xs" variant="link" @click="addSlide" />
        </c-tooltip>
        <c-dropdown-menu :items="menuItems">
          <c-button :icon="icons.more" size="xs" variant="link" />
        </c-dropdown-menu>
      </div>
    </div>
    <!-- The wait between slides, offered beside the menu that turns autoplay on rather than in it,
    since a number field inside a menu closes it on the first keystroke. -->
    <div
      v-if="slide != null && widget.autoplay"
      class="border-default flex justify-end border-t px-2 py-1"
    >
      <c-schema-form-value
        v-model="widget.interval"
        :schema="{ type: 'integer', title: 'Seconds Per Slide', minimum: 1, maximum: 3600 }"
      />
    </div>
  </div>
</template>

<style module>
/* Long enough to be followed across the width of a widget, and short enough not to be waited on. */
.travelling {
  transition: transform 260ms cubic-bezier(0.2, 0, 0, 1);
}

.offRight {
  transform: translateX(100%);
}

.offLeft {
  transform: translateX(-100%);
}

/* Small enough to sit under a slide without competing with it, and large enough to aim at. Drawn
in its own right rather than as a faded shade of whatever text colour it inherits, which left it
too near the band behind it to make out. */
.dot {
  position: relative;
  width: 9px;
  height: 9px;
  padding: 0;
  border: none;
  border-radius: 50%;
  margin: 0 1.5px;
  background-color: var(--ui-text-muted);
  cursor: pointer;
  transition:
    background-color 160ms ease-out,
    transform 160ms ease;
  touch-action: none;
}

.dot:hover {
  background-color: var(--ui-text);
}

.dotCurrent,
.dotCurrent:hover {
  background-color: var(--ui-primary);
}

.dotHeld {
  z-index: 2;
}

/* The held dot tracks the pointer directly so it must not smooth its own movement. The transition
returns on release and animates it into the gap. */
.dotGrabbed {
  cursor: grabbing;
  transition: background-color 160ms ease-out;
}

.dotSwapping {
  transition: none;
}

/* Drawn as an offer rather than as a dot, wearing the same dashed border and tint every drop
target wears so it reads as a place to let go rather than as a slide that already exists. */
.ghostDot {
  width: 30px;
  height: 14px;
  padding: 0;
  border: 2px dashed var(--ui-primary);
  border-radius: 7px;
  margin: 0 1.5px;
  background-color: color-mix(in srgb, var(--ui-primary) 10%, transparent);
}

/* The ring closes clockwise from the top, drawn as a circle whose dash is drawn back in over the
wait. An outline rather than a fill so the dot underneath still says which slide is showing. */
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
  overflow: visible;
  color: var(--ui-primary);
  pointer-events: none;
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
