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
import { useWidgetDrop } from '@/widget-drop'
import {
  convertedPagesWidget,
  useWorkspace,
  withFreshPage,
  TabsWidget,
  WidgetPage,
  WidgetRow,
} from '@/workspace'

const { widget, container } = defineProps<{
  widget: TabsWidget

  /** The workspace row this strip sits in, whose height is the height its tabs get. */
  container?: WidgetRow
}>()

const workspace = useWorkspace()
const drop = useWidgetDrop()

let index = $ref(0)

const shown = $computed(() => widget.tabs[index] ?? null)

// A tab is as tall as the strip's widget however little is on it, so the height left at the bottom
// goes somewhere. The last row is the default, being where a table or a chart wants the room.
const expandOptions = [
  { label: 'Last Widget Row', value: 'last' },
  { label: 'First Widget Row', value: 'first' },
  { label: 'All Widget Rows', value: 'even' },
  { label: "Don't Fill", value: 'none' },
]

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

// A widget carried over the strip is being brought to a tab rather than to the one on show, so
// the strip turns to whatever it is held over and the drop lands there. Held over for a moment
// first, since crossing the strip on the way somewhere else is not a change of mind.
const dwellBeforeTurning = 280

let turning: ReturnType<typeof setTimeout> | null = null

// What the wait is for, so travelling across a tab does not start it over on every step of the
// pointer. `undefined` is nothing waited for, and null is the room past the last tab.
let awaited: number | null | undefined = undefined

function stopTurning() {
  if (turning != null) {
    clearTimeout(turning)
    turning = null
  }

  awaited = undefined
}

function onStripPointerLeave() {
  stopTurning()
  ghost = false
}

/** Whichever tab the pointer is over, or null for the strip's own room past the end of them. */
function onStripPointerOver(event: PointerEvent) {
  if (workspace.drag == null) {
    return
  }

  const over = (event.target as HTMLElement | null)?.closest('.q-tab') ?? null
  const tabs = [...(root?.querySelectorAll<HTMLElement>('.q-tab') ?? [])]
  const at = over == null ? null : tabs.indexOf(over as HTMLElement)

  turnWhileDragging(at != null && at >= 0 ? at : null)
}

// A tab offered rather than made. Nothing but a drawing, so a workspace saved mid-drag holds no
// trace of it. It becomes a tab the moment a widget is let go of on it, and not before.
let ghost = $ref(false)

/** Take the widget in hand onto a tab of its own, made here and now for it to land on.

Runs on the ghost's own `pointerup`, which arrives before the drop system's window-level release,
so the tab exists and holds the widget by the time release runs. Release then finds nothing to do,
since the strip is no place a plain drop can land.
*/
function onGhostDrop() {
  const drag = workspace.drag
  if (drag == null || !drop.active) {
    return
  }

  const opened = { id: v7(), name: '', layout: [] }
  widget.tabs = [...widget.tabs, opened]
  workspace.moveWidgets(
    drag.widgets.map((held) => held.id),
    { layout: opened.id, row: 0, column: null }
  )
  show(widget.tabs.length - 1)
  ghost = false
}

// An offer not taken goes away with the drag that asked for it.
watch(
  () => workspace.drag != null,
  (dragging) => {
    if (!dragging) {
      ghost = false
    }
  }
)

function turnWhileDragging(at: number | null) {
  if (awaited === at) {
    return
  }

  stopTurning()
  awaited = at

  if (workspace.drag == null) {
    return
  }

  turning = setTimeout(async () => {
    turning = null
    awaited = undefined

    // A tab of its own for a widget dropped past the end of the strip or into a seam, since the
    // room between tabs is the one place a strip can be added to by carrying something to it.
    if (at == null) {
      ghost = true
      return
    }

    show(at)

    // The layout it turned to was never on screen when the drag was measured, so it has to be
    // measured before anything can be aimed at it.
    await nextTick()
    drop.remeasure()
  }, dwellBeforeTurning)
}

function onTabClick(at: number, event: MouseEvent) {
  // A press that turned into a drag has already done what it was for.
  if (reorder.consumeClick()) {
    return
  }

  // Shift names the tab rather than turning to it, which is what holding shift over one already
  // offers. The press is what makes the offer a real edit, so it outlasts shift being let go of.
  if (event.shiftKey) {
    startNaming(at)
    return
  }

  show(at)
}

/** Put the caret in a tab's name, wherever the asking came from. */
function startNaming(at: number) {
  editingId = widget.tabs[at]?.id ?? null
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
  // Never down to none, for the same reason a carousel keeps a slide: a strip holding no tabs has
  // no layout, so nothing could be dragged onto it or pasted into it.
  if (widget.tabs.length <= 1) {
    return
  }

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
  const carousel = convertedPagesWidget(widget)
  if (carousel != null) {
    workspace.replaceWidget(widget.id, carousel)
  }
}
</script>

<template>
  <div :class="[$style.root, 'column', 'full-height', 'no-wrap']">
    <!-- The strip answers a drag itself, by turning to whichever tab is held over or making a new
    one past the end, so it is no place to drop a widget beside the strip's own widget. -->
    <div
      ref="root"
      :class="[$style.strip, 'items-stretch', 'no-wrap', 'row']"
      data-no-drop
      @pointerleave="onStripPointerLeave"
      @pointerover="onStripPointerOver"
    >
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
          :data-drop-layout="workspace.drag != null ? current.id : undefined"
          :name="current.id"
          :style="reorder.styleFor(at)"
          v-bind="reorder.handlers(at)"
          @click="onTabClick(at, $event)"
          @contextmenu.stop
          @dblclick.stop="startNaming(at)"
          @keydown="onTabKeydown($event, at)"
        >
          <div
            :class="[$style.tabInner, 'items-center', 'no-wrap', 'row']"
            @dblclick.stop="startNaming(at)"
            @pointerenter="setNameHovered(current, true)"
            @pointerleave="setNameHovered(current, false)"
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
                <q-item v-close-popup clickable dense @click="startNaming(at)">
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
                <q-item
                  v-close-popup
                  clickable
                  dense
                  :disable="widget.tabs.length <= 1"
                  @click="deleteTab(at)"
                >
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
              v-if="widget.tabs.length > 1"
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
      <!-- The tab a drop past the end of the strip would make, drawn rather than made. Its own
      pointerup is what makes it real, so letting go anywhere else leaves no trace of it. -->
      <div
        v-if="ghost"
        :class="[$style.ghost, 'items-center', 'justify-center', 'row']"
        @pointerup="onGhostDrop"
      >
        <q-icon :name="icons.add" size="14px" />
      </div>
      <!-- Sits beside the last tab while there is room for it there, and pins to the trailing edge
      once the tabs have outgrown the strip and begun to scroll under it. Held back entirely while
      there are no tabs, since the empty strip asks for the first one itself and two of the same
      button on screen at once is one too many. -->
      <q-btn
        v-if="widget.tabs.length > 0"
        :class="[$style.add, overflowing && $style.addAnchored, 'q-ml-xs']"
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
            <!-- How the strip is drawn, rather than what is on any one tab, which is why these sit
            under a rule at the end. The menu stays open, since seeing the strip take the setting is
            the point of choosing it. -->
            <q-item dense>
              <q-item-section>
                <q-checkbox v-model="widget.fill" dense label="Fill Width" />
              </q-item-section>
            </q-item>
            <q-item v-if="widget.expand !== 'none'" dense>
              <q-item-section>
                <q-checkbox v-model="widget.shrink" dense label="Shrink" />
              </q-item-section>
            </q-item>
            <q-item dense>
              <q-item-section>
                <q-select
                  v-model="widget.expand"
                  dense
                  emit-value
                  label="Fill Tab Height"
                  map-options
                  :options="expandOptions"
                  options-dense
                  outlined
                />
              </q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </div>
    <q-separator />
    <!-- The same button a layout with nothing on it offers, so adding the first tab is the thing
    it already is everywhere else rather than something else to read. -->
    <div v-if="shown == null" :class="[$style.empty, 'col', 'column', 'flex-center']">
      <q-btn
        aria-label="Add Tab"
        color="primary"
        :icon="icons.add"
        round
        size="8px"
        unelevated
        @click="addTab"
      >
        <q-tooltip class="bg-primary text-white">Add Tab</q-tooltip>
      </q-btn>
    </div>
    <!-- A tab is a workspace in miniature, arranged through the same editor the workspace itself
    is drawn by, so everything that can be done to a layout can be done to one. -->
    <div v-else :class="[$style.body, 'overflow-auto', 'q-px-sm']">
      <workspace-layout
        :key="shown.id"
        :expand="widget.expand"
        :host="container"
        :layout="shown.layout"
        :layout-id="shown.id"
        :shrink="widget.shrink"
      />
    </div>
  </div>
</template>

<style lang="scss" module>
@use 'sass:color';
@use '@/css/tab-strip' as strip;

.empty {
  min-height: 60px;
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

// Drawn as an outline rather than as a tab, since it is being offered rather than made. Wide
// enough to be worth letting go over, and faded the way an unshown tab is.
.ghost {
  flex: 0 0 auto;
  min-width: 60px;
  opacity: 0.7;
  outline: 1px dashed currentColor;
  outline-offset: -2px;
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

// Clear of the strip's own menu, which is the one thing pinned further out than it.
.addAnchored {
  @include strip.addAnchored(30px);
}

:global(.dark) .addAnchored {
  background-color: $dark;
}

:global(.light) .addAnchored {
  background-color: color.adjust(white, $lightness: -1%);
}
</style>
