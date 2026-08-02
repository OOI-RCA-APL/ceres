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

const shown = $computed(() => widget.tabs[index] ?? null)

// Tabs can be taken away from under it, so the position is kept inside what is actually there.
watch(
  () => widget.tabs.length,
  (length) => {
    if (index >= length) {
      index = Math.max(0, length - 1)
    }
  }
)

// Turning to a tab is asking to work on it, so it becomes the layout a paste lands in and the one
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

    // The tab being looked at stays the tab being looked at, wherever it has just been put.
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
  moveTab(at, step)

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

// One menu per tab, reachable from the dots and from a right-click on the tab. Held by tab rather
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

// Tabs are added, named, arranged and taken away on the strip itself, since a tab is a layout and
// a layout is arranged by working on it rather than by describing it somewhere else.
function addTab() {
  widget.tabs = [...widget.tabs, { id: v7(), name: '', layout: [] }]
  show(widget.tabs.length - 1)
}

function deleteTab(at: number) {
  widget.tabs = widget.tabs.filter((_, position) => position !== at)
  show(Math.min(index, widget.tabs.length - 1))
}

// A tab copied carries copies of everything on it, since two things answering to one name would
// have whatever went looking take whichever it found first.
function duplicateTab(at: number) {
  const source = widget.tabs[at]
  if (source == null) {
    return
  }

  const tabs = [...widget.tabs]
  tabs.splice(at + 1, 0, withFreshPage(source))
  widget.tabs = tabs
  show(at + 1)
}

function moveTab(at: number, by: number) {
  const to = at + by
  if (to < 0 || to >= widget.tabs.length) {
    return
  }

  widget.tabs = moved([...widget.tabs], at, to)
  if (index === at) {
    index = to
  }
}

/** Turn this strip into a carousel holding the same tabs as its slides, in the same place. */
function convertToCarousel() {
  const carousel = createWidget('carousel') as CarouselWidget
  // A name that was only ever the default for a tab strip or a carousel is not a name anybody
  // chose, so it gives way to the new kind's own rather than following the tabs across.
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
        :class="[$style.tabs, widget.fill && $style.filling]"
        dense
        indicator-color="transparent"
        inline-label
        :model-value="shown?.id ?? null"
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
                :name="current.name !== '' ? current.name : `Tab ${at + 1}`"
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
                <q-item v-close-popup clickable dense @click="duplicateTab(at)">
                  <q-item-section avatar>
                    <q-icon :name="icons.duplicate" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Duplicate</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense :disable="at === 0" @click="moveTab(at, -1)">
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
                  @click="moveTab(at, 1)"
                >
                  <q-item-section avatar>
                    <q-icon :name="icons.menuRight" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Move Later</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense @click="deleteTab(at)">
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
              :class="[$style.close, current.id === shown?.id && $style.closeShown]"
              dense
              flat
              :icon="icons.close"
              round
              size="6.5px"
              @click.stop="deleteTab(at)"
              @mousedown.stop
              @touchstart.stop
            >
              <q-tooltip class="bg-primary text-white" :delay="500">Delete Tab</q-tooltip>
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
        @click="addTab"
      >
        <q-tooltip class="bg-primary text-white">Add Tab</q-tooltip>
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
            <q-separator />
            <!-- How the strip is drawn, rather than what is on any one tab, which is why it sits
            under a rule at the end. The menu stays open, since seeing the strip take the setting is
            the point of choosing it. -->
            <q-item dense>
              <q-item-section>
                <q-checkbox v-model="widget.fill" dense label="Fill Width" />
              </q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </div>
    <q-separator />
    <div v-if="shown == null" :class="[$style.empty, 'col', 'column', 'flex-center']">
      <common-text variant="description">A tab strip shows one tab at a time.</common-text>
      <q-btn
        class="q-mt-sm"
        color="primary"
        dense
        flat
        :icon="icons.add"
        label="Add Tab"
        no-caps
        size="sm"
        @click="addTab"
      />
    </div>
    <!-- A tab is a workspace in miniature, arranged through the same editor the workspace itself
    is drawn by, so everything that can be done to a layout can be done to one. -->
    <div v-else :class="[$style.body, 'overflow-auto', 'q-px-sm']">
      <workspace-layout :key="shown.id" :layout="shown.layout" :layout-id="shown.id" />
    </div>
  </div>
</template>

<style lang="scss" module>
@use 'sass:color';
@use '@/css/tab-strip' as strip;

.empty {
  opacity: 0.7;
}

// Takes the room left over rather than asking for the room its contents want, so the strip above it
// keeps its place however much a tab happens to hold.
.body {
  flex: 1 1 0;
  min-height: 0;

  // Room for the scrollbar whether or not one is showing, so a tab reflowing as rows are added
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
  @include strip.scroller;
}

// Tabs sharing out whatever room the strip has spare, rather than leaving it empty after the last
// one.
.filling {
  flex: 1 1 auto;

  :global(.q-tabs__content) {
    width: 100%;
  }

  // An equal share each, floored at the width the tab's own name needs. Asking for a share from
  // nothing rather than from its content is what makes the shares equal, and the floor is what
  // keeps a long name from being cut down to match a short one. A strip with no room to spare is
  // then every tab at its own width, which is exactly what it is without this.
  .tab {
    flex: 1 1 0;
    min-width: max-content;
  }

  // A name centred in the room it has been given, since a tab wider than its name is no longer a
  // label with space after it. On a full strip there is no spare room and this does nothing.
  .tabInner {
    justify-content: center;
  }
}

.tabs .tab {
  @include strip.tabUnpadded;
}

.tab :global(.q-tab__content) {
  @include strip.tabContentUnpadded;
}

.tab {
  @include strip.tab;
}

// The grip and the close button sit against the tab's own edges rather than inside the row, so they
// cost the same width whether they are showing or not and the label never moves.
.tabInner {
  height: 100%;
  padding: 2px 20px 2px 14px;
}

// Reaching only as far as the padding does, since a widget's tab carries no icon for the grip to
// have to clear.
.grip {
  @include strip.grip(14px);
}

.label {
  @include strip.label;
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

.close {
  @include strip.close;
}

// The tab being shown keeps its close button visible, since that is the one most likely to go
// next.
.tab:hover .close,
.closeShown {
  opacity: 1;
}

.arranging {
  @include strip.arranging;
}

.held {
  @include strip.held;
}

.grabbed {
  @include strip.grabbed;
}

.swapping {
  @include strip.swapping;
}

.add,
.stripMenu {
  @include strip.add;
  @include strip.fadedIcon;
}

.addCentered {
  @include strip.addCentered;
}

// Clear of the strip's own menu, which is the one thing pinned further out than it.
.addAnchored {
  @include strip.addAnchored(30px);
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
