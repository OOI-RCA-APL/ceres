<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { useResizeObserver } from '@vueuse/core'
import { v7 } from 'uuid'
import { nextTick, watch } from 'vue'

import strip from '@/assets/css/tab-strip.module.css'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { usePersisted } from '@/persistence'
import { moved, usePointerReorder } from '@/reorder'
import { useWidgetDrop } from '@/widget-drop'
import { convertedPagesWidget, useWorkspace, withFreshPage } from '@/workspace'
import type { TabsWidget, WidgetPage, WidgetRow } from '@/workspace'

const { widget, container } = defineProps<{
  widget: TabsWidget

  /** The workspace row this strip sits in, whose height is the height its tabs get. */
  container?: WidgetRow
}>()

const workspace = useWorkspace()
const drop = useWidgetDrop()

let index = $ref(0)

const shown = $computed(() => widget.tabs[index] ?? null)

// Which tab is open is this browser's own place in the workspace rather than part of it so it
// survives a reload here and goes nowhere else. Held as the tab's ID rather than its position, so
// tabs reordered or deleted from another seat cannot restore somebody else's tab.
const persisted = usePersisted({
  schema: (zod) => zod.object({ tab: zod.string().nullable().catch(null).default(null) }),
  methods: [{ type: 'local-storage', key: ['widget-tab', widget.id] }],
})

const remembered = widget.tabs.findIndex((tab) => tab.id === persisted.tab)
if (remembered >= 0) {
  // The position alone, without `show`, which would steal the workspace's focused layout on
  // every reload for every strip on it.
  index = remembered
}

watch(
  () => shown?.id ?? null,
  (id) => {
    persisted.tab = id
  },
)

// A tab is as tall as the strip's widget however little is on it so the height left at the bottom
// goes somewhere. The last row is the default, being where a table or a chart wants the room.
const expandOptions = [
  { label: 'Last Widget Row', value: 'last' },
  { label: 'First Widget Row', value: 'first' },
  { label: 'All Widget Rows', value: 'even' },
  { label: "Don't Fill", value: 'none' },
]

// Tabs can be taken away from under it so the position is kept inside what is actually there.
watch(
  () => widget.tabs.length,
  (length) => {
    if (index >= length) {
      index = Math.max(0, length - 1)
    }
  },
)

// Turning to a tab is asking to work on it so it becomes the layout a paste lands in and the one
// the keyboard acts on.
function show(at: number) {
  index = Math.min(Math.max(at, 0), Math.max(0, widget.tabs.length - 1))

  const opened = widget.tabs[index] ?? null
  if (opened != null) {
    workspace.focusLayout(opened.id)
  }
}

// The strip reorders by pointer rather than by the HTML5 drag API so it behaves the way browser
// tabs do, which is the same composable the workspace's own strip is driven by.
let rootElement = $ref<HTMLElement | null>(null)
let scrollerElement = $ref<HTMLElement | null>(null)

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(scrollerElement?.querySelectorAll<HTMLElement>('[data-tab]') ?? [])],
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
  // The strip scrolls once it outgrows its room so a tab held near either end carries the strip
  // along and can be taken past what is showing.
  scroller: () => scrollerElement,
})

// Whether the tabs have outgrown the strip, which decides where the add button sits since a strip
// with room can keep it beside the last tab while a scrolling one cannot.
let overflowing = $ref(false)

function measureOverflow() {
  overflowing =
    scrollerElement != null && scrollerElement.scrollWidth > scrollerElement.clientWidth + 1
}

useResizeObserver($$(rootElement), measureOverflow)

watch(
  () => widget.tabs.map((current) => current.id),
  async () => {
    await nextTick()
    measureOverflow()
  },
  { immediate: true },
)

// A widget carried over the strip is being brought to a tab rather than to the one on show, so
// the strip turns to whatever it is held over and the drop lands there. Held over for a moment
// first since crossing the strip on the way somewhere else is not a change of mind.
const dwellBeforeTurning = 280

let turning: ReturnType<typeof setTimeout> | null = null

// What the wait is for so travelling across a tab does not start it over on every step of the
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

  const over = (event.target as HTMLElement | null)?.closest('[data-tab]') ?? null
  const tabs = [...(scrollerElement?.querySelectorAll<HTMLElement>('[data-tab]') ?? [])]
  const at = over == null ? null : tabs.indexOf(over as HTMLElement)

  turnWhileDragging(at != null && at >= 0 ? at : null)
}

// A tab offered rather than made. Nothing but a drawing so a workspace saved mid-drag holds no
// trace of it. It becomes a tab the moment a widget is let go of on it, and not before.
let ghost = $ref(false)

/** Take the widget in hand onto a tab of its own, made here and now for it to land on.

Runs on the ghost's own `pointerup`, which arrives before the drop system's window-level release,
so the tab exists and holds the widget by the time release runs.
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
    { layout: opened.id, row: 0, column: null },
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
  },
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

    // A tab of its own for a widget dropped past the end of the strip since the room between tabs
    // is the one place a strip can be added to by carrying something to it.
    if (at == null) {
      ghost = true
      return
    }

    show(at)

    // The layout it turned to was never on screen when the drag was measured so it has to be
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

  // Shift renames the tab rather than turning to it. The press makes the rename a real edit, so
  // it outlasts shift being released.
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

  // The tab travels with the key so focus goes with it rather than staying on whatever has taken
  // its place.
  await nextTick()
  scrollerElement?.querySelectorAll<HTMLElement>('[data-tab]')[to]?.focus()
}

// Holding shift over a tab turns its name into a field in place so renaming is discoverable.
// Clicking into it makes it a real edit that survives shift being released.
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

// Tabs are added, named, arranged and taken away on the strip itself since a tab is a layout and
// a layout is arranged by working on it rather than by describing it somewhere else.
function addTab() {
  widget.tabs = [...widget.tabs, { id: v7(), name: '', layout: [] }]
  show(widget.tabs.length - 1)
}

function deleteTab(at: number) {
  // Never down to none, for the same reason a carousel keeps a slide: a strip holding no tabs has
  // no layout so nothing could be dragged onto it or pasted into it.
  if (widget.tabs.length <= 1) {
    return
  }

  widget.tabs = widget.tabs.filter((_, position) => position !== at)
  show(Math.min(index, widget.tabs.length - 1))
}

// A tab copied carries copies of everything on it since two things answering to one name would
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

// How the strip is drawn, rather than what is on any one tab, which is why these sit below a rule.
const stripMenuItems = $computed<DropdownMenuItem[][]>(() => [
  [{ label: 'Convert To Carousel', icon: icons.carousel, onSelect: convertToCarousel }],
  [
    {
      label: 'Fill Width',
      type: 'checkbox',
      checked: widget.fill,
      onUpdateChecked: (value: boolean) => (widget.fill = value),
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
      label: 'Fill Tab Height',
      children: expandOptions.map((option) => ({
        label: option.label,
        type: 'checkbox' as const,
        checked: widget.expand === option.value,
        onUpdateChecked: () => (widget.expand = option.value as TabsWidget['expand']),
      })),
    },
  ],
])

function tabMenuItems(at: number): DropdownMenuItem[][] {
  return [
    [
      { label: 'Rename', icon: icons.rename, onSelect: () => startNaming(at) },
      { label: 'Duplicate', icon: icons.duplicate, onSelect: () => duplicateTab(at) },
    ],
    [
      {
        label: 'Delete',
        icon: icons.delete,
        disabled: widget.tabs.length <= 1,
        onSelect: () => deleteTab(at),
      },
    ],
  ]
}
</script>

<template>
  <div class="flex h-full flex-col flex-nowrap">
    <!-- The strip answers a drag itself, by turning to whichever tab is held over or making a new
    one past the end so it is no place to drop a widget beside the strip's own widget. -->
    <div
      ref="rootElement"
      class="border-default relative flex min-w-0 flex-nowrap items-stretch overflow-hidden border-b px-1 pt-1"
      data-no-drop
      @pointerleave="onStripPointerLeave"
      @pointerover="onStripPointerOver"
    >
      <div
        ref="scrollerElement"
        class="flex min-w-0 flex-nowrap items-stretch"
        :class="[strip.scroller, widget.fill && 'w-full']"
      >
        <!-- Middle-click closes a tab, the way it does in a browser, whose tab idioms this strip
        already borrows. The press itself is swallowed so the browser's middle-press autoscroll
        never engages on a strip that scrolls. -->
        <c-context-menu
          v-for="(current, at) in widget.tabs"
          :key="current.id"
          :items="tabMenuItems(at)"
        >
          <div
            :aria-selected="current.id === shown?.id"
            :class="[
              strip.tab,
              current.id === shown?.id && strip.activeTab,
              reorder.isSwapping && strip.swapping,
              reorder.isDragging && strip.arranging,
              reorder.isHeld(at) && strip.held,
              reorder.isGrabbed(at) && strip.grabbed,
              widget.fill && 'min-w-max flex-1',
            ]"
            :data-drop-layout="workspace.drag != null ? current.id : undefined"
            data-tab
            role="tab"
            :style="reorder.styleFor(at)"
            tabindex="0"
            v-bind="reorder.handlers(at)"
            @click="onTabClick(at, $event)"
            @dblclick.stop="startNaming(at)"
            @keydown="onTabKeydown($event, at)"
            @mousedown.middle.prevent.stop
            @mouseup.middle.stop="deleteTab(at)"
          >
            <div
              class="relative flex h-full flex-nowrap items-center pr-5 pl-[14px]"
              :class="widget.fill && 'justify-center'"
              @pointerenter="setNameHovered(current, true)"
              @pointerleave="setNameHovered(current, false)"
            >
              <!-- The tab's leading edge carries the grab cursor, which is all a tab needs to say
              it can be dragged since a strip of tabs already reads as one. -->
              <span :class="strip.grip" />
              <c-text class="whitespace-nowrap" variant="th">
                <c-inline-name-edit
                  :claim="editingId === current.id"
                  :editing="isNaming(current)"
                  :name="current.name !== '' ? current.name : `Tab ${at + 1}`"
                  @rename="(value: string) => (current.name = value)"
                  @update:editing="(value: boolean) => (editingId = value ? current.id : null)"
                />
              </c-text>
              <c-dropdown-menu :items="tabMenuItems(at)">
                <button
                  class="ml-1 flex items-center rounded-full opacity-60 hover:opacity-100"
                  type="button"
                  @click.stop
                  @mousedown.stop
                  @pointerdown.stop
                  @touchstart.stop
                >
                  <c-icon :name="icons.more" size="13" />
                </button>
              </c-dropdown-menu>
              <c-tooltip :delay-duration="500" text="Delete Tab">
                <button
                  v-if="widget.tabs.length > 1"
                  :class="[strip.close, current.id === shown?.id && strip.closeShown]"
                  type="button"
                  @click.stop="deleteTab(at)"
                  @mousedown.stop
                  @pointerdown.stop
                  @touchstart.stop
                >
                  <c-icon :name="icons.close" size="13" />
                </button>
              </c-tooltip>
            </div>
          </div>
        </c-context-menu>
      </div>
      <!-- The tab a drop past the end of the strip would make, drawn rather than made. Its own
      pointerup is what makes it real so letting go anywhere else leaves no trace of it. -->
      <div
        v-if="ghost"
        class="text-primary border-primary bg-primary/10 flex min-w-[60px] flex-none items-center justify-center rounded border-2 border-dashed"
        @pointerup="onGhostDrop"
      >
        <c-icon :name="icons.add" size="14" />
      </div>
      <!-- Sits beside the last tab while there is room for it there, and pins to the trailing edge
      once the tabs have outgrown the strip and begun to scroll under it. Held back entirely while
      there are no tabs since the empty strip asks for the first one itself. -->
      <c-tooltip text="Add Tab">
        <button
          v-if="widget.tabs.length > 0"
          class="bg-default text-muted hover:text-default z-[2] flex w-[26px] flex-none items-center justify-center"
          :class="overflowing ? 'absolute inset-y-0 right-[26px]' : 'ml-1 self-stretch'"
          type="button"
          @click="addTab"
        >
          <c-icon :name="icons.add" size="16" />
        </button>
      </c-tooltip>
      <c-dropdown-menu :items="stripMenuItems">
        <button
          class="bg-default text-muted hover:text-default z-[2] flex w-[26px] flex-none items-center justify-center self-stretch"
          type="button"
        >
          <c-icon :name="icons.more" size="16" />
        </button>
      </c-dropdown-menu>
    </div>
    <!-- The same button a layout with nothing on it offers so adding the first tab is the thing
    it already is everywhere else rather than something else to read. -->
    <div v-if="shown == null" class="flex min-h-[60px] flex-1 flex-col items-center justify-center">
      <c-tooltip text="Add Tab">
        <c-button
          aria-label="Add Tab"
          class="rounded-full"
          color="primary"
          :icon="icons.add"
          size="xs"
          @click="addTab"
        />
      </c-tooltip>
    </div>
    <!-- A tab is a workspace in miniature, arranged through the same editor the workspace itself
    is drawn by so everything that can be done to a layout can be done to one. -->
    <!-- The gutter is held whether or not a scrollbar shows, so widgets at the right edge do not
    jump under the hand arranging them as rows are added. -->
    <div v-else class="min-h-0 flex-1 overflow-auto px-2 [scrollbar-gutter:stable]">
      <c-workspace-layout
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
