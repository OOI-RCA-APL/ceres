<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { nextTick, onMounted, watchEffect } from 'vue'

/** A virtual scroller for rows that are all the same known height.

A measuring scroller pays for generality: each redraw reads the height of every row it is
showing, which forces a layout, and then corrects the scroll position from what it measured.
A record is one line of a fixed height so none of that is needed. Which rows to show is
division, the space above and below them is multiplication, and neither reads anything back
out of the page. That makes it cheap enough to do on every scroll so there is never a moment
with nothing drawn, and it never moves the scroll position so the scrollbar stays put.
*/
const {
  items,
  itemSize,
  overscan = 2,
} = defineProps<{
  items: readonly unknown[]
  itemSize: number

  /** Screenfuls kept drawn above and below so a scroll has somewhere drawn to arrive into. */
  overscan?: number
}>()

let table = $ref<HTMLTableElement | null>(null)
let start = $ref(0)
let viewport = $ref(0)

/** The scrolling element, the table itself. */
const scroller = $computed<HTMLElement | null>(() => table)

function onScroll() {
  const box = scroller
  if (box == null) {
    return
  }

  start = box.scrollTop

  // Normally the observer below says how tall the box is. Until it has said anything, and
  // anywhere it never does, this is what keeps the scroller believing it has room to draw.
  if (viewport === 0) {
    viewport = box.clientHeight
  }
}

// Where the scroller already stands when it first appears, which is not always the top of
// the list: a record view opens at the newest record.
onMounted(() => {
  const box = scroller
  if (box != null) {
    viewport = box.clientHeight
    start = box.scrollTop
  }
})

useResizeObserver(
  () => scroller,
  (entries) => {
    for (const entry of entries) {
      viewport = entry.contentRect.height
    }
  },
)

const rowsInView = $computed(() => Math.max(1, Math.ceil(viewport / itemSize)))
const buffer = $computed(() => Math.ceil(rowsInView * overscan))

// How many rows of travel the drawn window ignores before it moves. Redrawing at every row
// would relayout the table on nearly every frame of a scroll, and the stutter of that shows
// in the scrollbar even when the rows themselves glide. Between steps nothing in here
// changes at all, so the browser scrolls composited content and touches no layout. The
// buffer is what makes the coarseness safe, being several times deeper than a step.
const stride = 8

const from = $computed(() => {
  const stepped = Math.floor(Math.floor(start / itemSize) / stride) * stride
  return Math.max(0, stepped - buffer)
})
const to = $computed(() => {
  const stepped = Math.floor(Math.floor(start / itemSize) / stride) * stride
  return Math.min(items.length, stepped + stride + rowsInView + buffer)
})

const shown = $computed(() => items.slice(from, to))
const above = $computed(() => from * itemSize)
const below = $computed(() => Math.max(0, items.length - to) * itemSize)

// The spacers stand in for rows so each reaches across as many columns as a row turned out
// to hold. Counted off a drawn row rather than declared since what a row holds is the
// caller's.
let content = $ref<HTMLElement | null>(null)
let columns = $ref(1)

watchEffect(() => {
  // Read so this runs again whenever the rows are redrawn.
  void shown

  nextTick(() => {
    const cells = content?.querySelector('tr')?.children.length ?? 0
    if (cells > 0) {
      columns = cells
    }
  })
})

function keyFor(item: unknown, index: number) {
  const id = (item as { id?: unknown } | null)?.id
  return typeof id === 'string' || typeof id === 'number' ? id : index
}

/** Move to `top`, and draw for there in the same breath.

A scroll the user makes is heard about through an event, which is soon enough because the
position has only moved as far as a hand can move it. A move made in code goes as far as it
likes, and the event announcing it arrives a frame later so drawing for the old position in
the meantime leaves whatever the jump crossed undrawn. Setting both together keeps that
frame from being blank.
*/
function moveTo(top: number) {
  const box = scroller
  if (box == null) {
    return
  }

  box.scrollTop = top

  // Read back rather than assumed since the box clamps what it was asked for to what it has.
  start = box.scrollTop
}

/** Put row `index` on screen, which is all that following the newest record needs. */
function scrollTo(index: number) {
  moveTo(Math.max(0, Math.min(index, items.length)) * itemSize)
}

/** Nothing is measured so there is nothing to measure again. Kept for the callers that ask. */
function refresh() {}

defineExpose({ scrollTo, moveTo, refresh, element: $$(scroller) })
</script>

<template>
  <table ref="table" :class="$style.root" @scroll.passive="onScroll">
    <tbody>
      <tr>
        <td :colspan="columns" :style="{ height: `${above}px`, padding: 0 }" />
      </tr>
    </tbody>
    <tbody ref="content">
      <template v-for="(item, offset) in shown" :key="keyFor(item, from + offset)">
        <slot :index="from + offset" :item="item" />
      </template>
    </tbody>
    <tbody>
      <tr>
        <td :colspan="columns" :style="{ height: `${below}px`, padding: 0 }" />
      </tr>
    </tbody>
  </table>
</template>

<style module>
.root {
  display: block;
  overflow: auto;
  border-collapse: separate;
  border-spacing: 0;
}

/* Each band lays itself out, since the anonymous table a scrolling block would otherwise wrap them
in shrinks to its content and leaves the last column short of the edge. Wide rows still overflow
and scroll, `max-content` winning over the floor. */
.root > tbody {
  display: table;
  width: max-content;
  min-width: 100%;
}

/* The browser must not anchor the scroll against anything in here. Chrome holds the content
under the eye still when layout above it changes, by silently moving the scroll position, and
here the layout above changes on every step of a scroll because that is what virtualization
is: the top spacer gives up a row's height and the row takes its place. Anchored on the table
or a spacer, that reads as the content jumping, and the correction feeds itself, so a small
upward scroll accelerates to the top of the list on its own. The scroller keeps the content
still by its own arithmetic so the browser has nothing to correct. */
.root,
.root * {
  overflow-anchor: none;
}
</style>
