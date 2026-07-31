<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { QMenu } from 'quasar'
import { v7 } from 'uuid'
import { nextTick, watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import WorkspaceLayout from '@/components/WorkspaceLayout.vue'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { moved, usePointerReorder } from '@/reorder'
import {
  createWidget,
  defaultWidgetName,
  useWorkspace,
  withFreshPage,
  CarouselWidget,
  TabsWidget,
  WidgetPage,
} from '@/workspace'

const { widget } = defineProps<{
  widget: TabsWidget
}>()

const workspace = useWorkspace()

let index = $ref(0)

const page = $computed(() => widget.tabs[index] ?? null)

// Pages can be taken away from under it, so the position is kept inside what is actually there.
watch(
  () => widget.tabs.length,
  (length) => {
    if (index >= length) {
      index = Math.max(0, length - 1)
    }
  }
)

// Turning to a page is asking to work on it, so it becomes the layout a paste lands in and the one
// the keyboard acts on.
function show(at: number) {
  index = Math.min(Math.max(at, 0), Math.max(0, widget.tabs.length - 1))

  const shown = widget.tabs[index] ?? null
  if (shown != null) {
    workspace.focusLayout(shown.id)
  }
}

// The strip reorders by pointer rather than by the HTML5 drag API, so it behaves the way browser
// tabs do, which is the same composable the workspace's own strip is driven by.
let root = $ref<HTMLElement | null>(null)

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(root?.querySelectorAll<HTMLElement>('.q-tab') ?? [])],
  onReorder: (from, to) => {
    widget.tabs = moved([...widget.tabs], from, to)

    // The page being looked at stays the page being looked at, wherever it has just been put.
    if (index === from) {
      index = to
    } else if (index > from && index <= to) {
      index--
    } else if (index < from && index >= to) {
      index++
    }
  },
  // The strip scrolls once it outgrows its room, so a tab held near either end carries the strip
  // along and can be taken past what is showing.
  scroller: () => root?.querySelector<HTMLElement>('.q-tabs__content') ?? null,
})

// Whether the tabs have outgrown the strip and started scrolling. It decides where the add button
// sits, since a strip with room can keep it beside the last tab while a scrolling one cannot.
let overflowing = $ref(false)

function measureOverflow() {
  const content = root?.querySelector('.q-tabs__content')
  overflowing = content != null && content.scrollWidth > content.clientWidth + 1
}

useResizeObserver($$(root), measureOverflow)

watch(
  () => widget.tabs.map((current) => current.id),
  async () => {
    await nextTick()
    measureOverflow()
  },
  { immediate: true }
)

function onTabClick(at: number) {
  // A press that turned into a drag has already done what it was for.
  if (reorder.consumeClick()) {
    return
  }

  show(at)
}

// Shift with an arrow key arranges the strip from the keyboard, the same as dragging a tab does
// with the pointer. Without shift the arrows belong to the strip itself, which steers between tabs.
async function onTabKeydown(event: KeyboardEvent, at: number) {
  if (!event.shiftKey) {
    return
  }

  const step = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  const to = at + step
  if (step === 0 || to < 0 || to >= widget.tabs.length) {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  movePage(at, step)

  // The tab travels with the key, so focus goes with it rather than staying on whatever has taken
  // its place.
  await nextTick()
  root?.querySelectorAll<HTMLElement>('.q-tab')[to]?.focus()
}

// Holding shift over a tab turns its name into a field there and then, so renaming is offered
// rather than hidden behind a shortcut nobody would guess. Clicking into it makes it a real edit,
// which is what keeps it once shift is let go of.
const { shift: shiftHeld } = useModifiers()

let hoveredId = $ref<string | null>(null)
let editingId = $ref<string | null>(null)

function setNameHovered(current: WidgetPage, hovered: boolean) {
  if (hovered) {
    hoveredId = current.id
  } else if (hoveredId === current.id) {
    hoveredId = null
  }
}

function isNaming(current: WidgetPage): boolean {
  return editingId === current.id || (shiftHeld.value && hoveredId === current.id)
}

// One menu per tab, reachable from the dots and from a right-click on the tab. Held by page rather
// than by position, since dragging renumbers the strip.
const menus = new Map<string, QMenu>()

function setMenu(id: string, element: QMenu | null) {
  if (element == null) {
    menus.delete(id)
  } else {
    menus.set(id, element)
  }
}

function showMenu(id: string, event: Event) {
  menus.get(id)?.show(event)
}

// Pages are added, named, arranged and taken away on the strip itself, since a page is a layout and
// a layout is arranged by working on it rather than by describing it somewhere else.
function addPage() {
  widget.tabs = [...widget.tabs, { id: v7(), name: '', layout: [] }]
  show(widget.tabs.length - 1)
}

function deletePage(at: number) {
  widget.tabs = widget.tabs.filter((_, position) => position !== at)
  show(Math.min(index, widget.tabs.length - 1))
}

// A page copied carries copies of everything on it, since two things answering to one name would
// have whatever went looking take whichever it found first.
function duplicatePage(at: number) {
  const source = widget.tabs[at]
  if (source == null) {
    return
  }

  const pages = [...widget.tabs]
  pages.splice(at + 1, 0, withFreshPage(source))
  widget.tabs = pages
  show(at + 1)
}

function movePage(at: number, by: number) {
  const to = at + by
  if (to < 0 || to >= widget.tabs.length) {
    return
  }

  widget.tabs = moved([...widget.tabs], at, to)
  if (index === at) {
    index = to
  }
}

/** Turn this strip into a carousel holding the same pages, in the same place. */
function convertToCarousel() {
  const carousel = createWidget('carousel') as CarouselWidget
  // A name that was only ever the default for a tab strip or a carousel is not a name anybody
  // chose, so it gives way to the new kind's own rather than following the pages across.
  if (widget.name !== defaultWidgetName('tabs')) {
    carousel.name = widget.name
  }

  carousel.slides = widget.tabs

  workspace.replaceWidget(widget.id, carousel)
}
</script>

<template>
  <div :class="[$style.root, 'column', 'full-height', 'no-wrap']">
    <div ref="root" :class="[$style.strip, 'items-stretch', 'no-wrap', 'row']">
      <q-tabs
        :class="$style.tabs"
        dense
        indicator-color="transparent"
        inline-label
        :model-value="page?.id ?? null"
        no-caps
        shrink
      >
        <q-tab
          v-for="(current, at) in widget.tabs"
          :key="current.id"
          :class="[
            $style.tab,
            reorder.isSwapping && $style.swapping,
            reorder.isDragging && $style.arranging,
            reorder.isHeld(at) && $style.held,
            reorder.isGrabbed(at) && $style.grabbed,
          ]"
          :name="current.id"
          :style="reorder.styleFor(at)"
          v-bind="reorder.handlers(at)"
          @click="onTabClick(at)"
          @keydown="onTabKeydown($event, at)"
        >
          <div
            :class="[$style.tabInner, 'items-center', 'no-wrap', 'row']"
            @dblclick.stop="editingId = current.id"
          >
            <!-- The tab's leading edge carries the grab cursor, which is all a tab needs to say it
            can be dragged, since a strip of tabs already reads as one. The whole tab is the drag
            target, so this is a hint rather than a handle. -->
            <span :class="$style.grip" />
            <common-text :class="$style.label" variant="th">
              <inline-name-edit
                :claim="editingId === current.id"
                :editing="isNaming(current)"
                :name="current.name !== '' ? current.name : `Page ${at + 1}`"
                @rename="(value: string) => (current.name = value)"
                @update:editing="(value: boolean) => (editingId = value ? current.id : null)"
              />
            </common-text>
            <span :class="$style.nameHover" @pointerenter="setNameHovered(current, true)" />
            <q-btn
              class="faded-hover q-ml-xs"
              dense
              flat
              :icon="icons.more"
              round
              size="6.5px"
              @click.stop="showMenu(current.id, $event)"
              @mousedown.stop
              @touchstart.stop
            />
            <!-- One menu per tab, opened by the dots or by right-clicking the tab itself, which is
            where a context menu is looked for first. -->
            <q-menu :ref="(element: any) => setMenu(current.id, element)" context-menu>
              <q-list bordered dense>
                <q-item v-close-popup clickable dense @click="editingId = current.id">
                  <q-item-section avatar>
                    <q-icon :name="icons.rename" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Rename</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-close-popup clickable dense @click="duplicatePage(at)">
                  <q-item-section avatar>
                    <q-icon :name="icons.duplicate" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Duplicate</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense :disable="at === 0" @click="movePage(at, -1)">
                  <q-item-section avatar>
                    <q-icon :name="icons.menuLeft" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Move Earlier</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  dense
                  :disable="at === widget.tabs.length - 1"
                  @click="movePage(at, 1)"
                >
                  <q-item-section avatar>
                    <q-icon :name="icons.menuRight" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Move Later</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense @click="deletePage(at)">
                  <q-item-section avatar>
                    <q-icon :name="icons.delete" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Delete</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
            <q-btn
              class="faded-hover"
              :class="[$style.close, current.id === page?.id && $style.closeShown]"
              dense
              flat
              :icon="icons.close"
              round
              size="6.5px"
              @click.stop="deletePage(at)"
              @mousedown.stop
              @touchstart.stop
            >
              <q-tooltip class="bg-primary text-white" :delay="500">Delete Page</q-tooltip>
            </q-btn>
          </div>
        </q-tab>
      </q-tabs>
      <!-- Sits beside the last tab while there is room for it there, takes the middle of an empty
      strip rather than hugging an edge with nothing next to it, and pins to the trailing edge once
      the tabs have outgrown the strip and begun to scroll under it. -->
      <q-btn
        :class="[
          $style.add,
          widget.tabs.length === 0 && $style.addCentered,
          widget.tabs.length > 0 && overflowing && $style.addAnchored,
          'q-ml-xs',
        ]"
        dense
        flat
        :icon="icons.add"
        round
        size="sm"
        @click="addPage"
      >
        <q-tooltip class="bg-primary text-white">Add Page</q-tooltip>
      </q-btn>
      <q-btn :class="$style.stripMenu" dense flat :icon="icons.more" round size="sm">
        <q-menu>
          <q-list bordered dense>
            <q-item v-close-popup clickable dense @click="convertToCarousel">
              <q-item-section avatar>
                <q-icon :name="icons.carousel" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Convert To Carousel</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </div>
    <q-separator />
    <div v-if="page == null" :class="[$style.empty, 'col', 'column', 'flex-center']">
      <common-text variant="description">A tab strip shows one page at a time.</common-text>
      <q-btn
        class="q-mt-sm"
        color="primary"
        dense
        flat
        :icon="icons.add"
        label="Add Page"
        no-caps
        size="sm"
        @click="addPage"
      />
    </div>
    <!-- A page is a workspace in miniature, arranged through the same editor the workspace itself
    is drawn by, so everything that can be done to a layout can be done to one. -->
    <div v-else :class="[$style.page, 'overflow-auto', 'q-px-sm']">
      <workspace-layout :key="page.id" :layout="page.layout" :layout-id="page.id" />
    </div>
  </div>
</template>

<style lang="scss" module>
@use 'sass:color';

.empty {
  opacity: 0.7;
}

// Takes the room left over rather than asking for the room its contents want, so the strip above it
// keeps its place however much a page happens to hold.
.page {
  flex: 1 1 0;
  min-height: 0;

  // Room for the scrollbar whether or not one is showing, so a page reflowing as rows are added
  // does not leave the widgets at its right edge jumping under the hand arranging them.
  scrollbar-gutter: stable;
}

// The strip carries the tabs and the buttons at the end of it, and nothing is drawn outside it.
.strip {
  position: relative;
  min-width: 0;
  padding: 3px 4px 0;
  overflow: hidden;
}

:global(.light) .strip {
  background-color: color.adjust(white, $lightness: -1%);
}

.tabs {
  height: 100%;
  flex: 0 1 auto;
  min-width: 0;
}

// A strip that outgrows its container scrolls, the way a browser's tab bar does. Quasar's own
// answer is a pair of arrow buttons, which cost width and sit awkwardly next to draggable tabs.
.tabs :global(.q-tabs__content) {
  overflow-x: auto;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

.tabs :global(.q-tabs__arrow) {
  display: none;
}

// Quasar's dense tabs impose a minimum height on the tab and pad its content box, which together
// push the tab taller than the strip it sits in. Both need matching specificity to override.
.tabs .tab {
  min-height: 0;
  padding: 0;
}

.tab :global(.q-tab__content) {
  padding: 0;
}

.tab {
  border-radius: 4px 4px 0 0;
  opacity: 0.7;
  transition: background-color 0.2s, opacity 0.2s, transform 0.16s ease;
  touch-action: none;

  &:hover {
    opacity: 1;
  }

  &:global(.q-tab--active) {
    opacity: 1;
    background-color: $primary;
    color: white;
  }
}

// The grip and the close button sit against the tab's own edges rather than inside the row, so they
// cost the same width whether they are showing or not and the label never moves under the pointer.
.tabInner {
  height: 100%;
  padding: 2px 20px 2px 14px;
}

// An invisible strip along the tab's leading edge carrying the grab cursor. Nothing is drawn in it,
// so it costs no width and the label never moves.
.grip {
  position: absolute;
  z-index: 1;
  top: 0;
  bottom: 0;
  left: 0;
  width: 14px;
  cursor: grab;
}

.label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// The name is offered as a field on hover, and the label itself is the wrong thing to ask, since a
// name being edited is a field rather than the text the pointer entered.
.nameHover {
  position: absolute;
  z-index: 1;
  top: 0;
  bottom: 0;
  left: 14px;
  right: 20px;
  pointer-events: none;
}

// The close button holds its place whether or not it is showing, so a tab stays exactly as wide
// hovered as it is at rest and the strip does not shuffle under the pointer. The page being shown
// keeps it visible, since that is the one most likely to go next.
.close {
  position: absolute;
  top: 50%;
  right: 4px;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.15s;
}

.tab:hover .close,
.closeShown {
  opacity: 1;
}

// While a drag is in progress the strip must not clip the lifted tab, and hover highlighting on the
// tabs sliding aside would read as a second thing happening at once.
.arranging {
  &:hover {
    opacity: inherit;
  }
}

.held {
  z-index: 2;
  opacity: 1;
}

// The held tab tracks the pointer directly, so it must not smooth its own movement. It regains the
// transition once released, which is what animates it into the gap.
.grabbed {
  cursor: grabbing;
  transition: background-color 0.2s, opacity 0.2s;
}

.swapping {
  transition: none;
}

.add,
.stripMenu {
  align-self: center;
  flex: none;
  border-radius: 50%;
}

// An empty strip has nothing for the button to sit against, so it takes the middle instead.
.addCentered {
  margin: 0 auto;
}

// Once the tabs scroll there is no end of the row to sit beside, so the button pins to the trailing
// edge with that side squared off against it, over the strip's own surface so the tabs read as
// passing underneath.
.addAnchored {
  position: absolute;
  top: 50%;
  right: 30px;
  z-index: 2;
  border-radius: 50% 0 0 50%;
  transform: translateY(-50%);
}

.add :global(.q-icon),
.stripMenu :global(.q-icon) {
  opacity: 0.7;
}

.add:hover :global(.q-icon),
.stripMenu:hover :global(.q-icon) {
  opacity: 1;
}

:global(.dark) .addAnchored,
:global(.dark) .addCentered {
  background-color: $dark;
}

:global(.light) .addAnchored,
:global(.light) .addCentered {
  background-color: color.adjust(white, $lightness: -1%);
}
</style>
