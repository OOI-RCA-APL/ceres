<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { nextTick, onMounted, watchEffect } from 'vue'

/** A virtual scroller for rows that are all the same known height.

Quasar's own scroller earns its keep on rows it has to measure, and pays for it: each redraw reads
the height of every row it is showing, which forces a layout, and then corrects the scroll position
from what it measured. Both are why it only redraws once the scrolling has stopped, and why the
rows under a moving scrollbar are blank until it does.

A record is one line of a fixed height, so none of that is needed. Which rows to show is division,
the space above and below them is multiplication, and neither reads anything back out of the page.
That makes it cheap enough to do on every scroll, so there is never a moment with nothing drawn,
and it never moves the scroll position, so the scrollbar stays where it is put.
*/
const {
  items,
  itemSize,
  overscan = 2,
} = defineProps<{
  items: readonly unknown[]
  itemSize: number

  /** Screenfuls kept drawn above and below, so a scroll has somewhere drawn to arrive into. */
  overscan?: number
}>()

let table = $ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
let start = $ref(0)
let viewport = $ref(0)

/** The scrolling element, which is the table itself, however the ref happens to hold it. */
const scroller = $computed<HTMLElement | null>(() => {
  if (table == null) {
    return null
  }

  const held = '$el' in table ? table.$el : table
  return held instanceof HTMLElement ? held : null
})

function onScroll() {
  const box = scroller
  if (box == null) {
    return
  }

  start = box.scrollTop

  // Normally the observer below says how tall the box is. Until it has said anything, and anywhere
  // it never does, this is what keeps the scroller from believing it has no room to draw into.
  if (viewport === 0) {
    viewport = box.clientHeight
  }
}

// Where the scroller already stands when it first appears, which is not always the top of the
// list: a record view opens at the newest record.
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
  }
)

const rowsInView = $computed(() => Math.max(1, Math.ceil(viewport / itemSize)))
const buffer = $computed(() => Math.ceil(rowsInView * overscan))

const from = $computed(() => Math.max(0, Math.floor(start / itemSize) - buffer))
const to = $computed(() =>
  Math.min(items.length, Math.ceil((start + viewport) / itemSize) + buffer)
)

const shown = $computed(() => items.slice(from, to))
const above = $computed(() => from * itemSize)
const below = $computed(() => Math.max(0, items.length - to) * itemSize)

// The spacers stand in for rows, so each reaches across as many columns as a row turned out to
// hold. Counted off a drawn row rather than declared, since what a row holds is the caller's.
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

/** Put row `index` on screen, which is the whole of what following the newest record needs. */
function scrollTo(index: number) {
  const box = scroller
  if (box == null) {
    return
  }

  box.scrollTop = Math.max(0, Math.min(index, items.length)) * itemSize
}

/** Nothing is measured, so there is nothing to measure again. Kept for the callers that ask. */
function refresh() {}

defineExpose({ scrollTo, refresh, element: $$(scroller) })
</script>

<template>
  <q-markup-table
    ref="table"
    class="q-virtual-scroll q-virtual-scroll--vertical scroll"
    dense
    flat
    separator="cell"
    square
    @scroll.passive="onScroll"
  >
    <tbody class="q-virtual-scroll__padding">
      <tr>
        <td :colspan="columns" :style="{ height: `${above}px` }" />
      </tr>
    </tbody>
    <tbody ref="content" class="q-virtual-scroll__content">
      <template v-for="(item, offset) in shown" :key="keyFor(item, from + offset)">
        <slot :index="from + offset" :item="item" />
      </template>
    </tbody>
    <tbody class="q-virtual-scroll__padding">
      <tr>
        <td :colspan="columns" :style="{ height: `${below}px` }" />
      </tr>
    </tbody>
  </q-markup-table>
</template>
