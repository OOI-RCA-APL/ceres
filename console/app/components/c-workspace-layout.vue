<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { onMounted } from 'vue'

import icons from '@/icons'
import { useWidgetDrop } from '@/widget-drop'
import {
  getWidgetInfo,
  type LayoutExpand,
  resolveWidgetWidths,
  useWorkspace,
  type Widget,
  widgetInfos,
  type WidgetRow,
  widgetWidthSubdivisions,
} from '@/workspace'

const {
  layout,
  layoutId,
  expand = 'none',
  shrink = false,
  host,
} = defineProps<{
  /** The rows this editor arranges. Written in place so it is the layout itself. */
  layout: WidgetRow[]

  /** The ID a drag targets this layout by. */
  layoutId: string

  /** What to do with height the layout has been given and its rows have not claimed.

  The default suits the workspace's own layout, which is as tall as its contents and has none
  left over.
  */
  expand?: LayoutExpand

  /** Whether rows may be squeezed below their own heights so that everything fits without
  scrolling. Only meaningful where the layout has a height of its own to fit into. */
  shrink?: boolean

  /** The row this whole layout is drawn inside, where there is one.

  A filling row's own height is not what renders so a vertical drag resizes this instead.
  */
  host?: WidgetRow
}>()

const workspace = useWorkspace()
const drop = useWidgetDrop()

const element = $ref<HTMLDivElement | null>(null)
let layoutWidth = $ref<number | null>(null)

// A mounted layout is a drag target. A carousel slide not being shown never registers.
drop.register({
  id: layoutId,
  rows: () => layout,
  element: () => element,
})

useResizeObserver($$(element), (resizes) => {
  for (const resize of resizes) {
    // With no room yet, report nothing rather than zero, which would pin every widget to
    // nothing until the next measurement.
    const width = resize.contentRect.width
    layoutWidth = width > 0 ? width : null
  }
})

/** The rows a drop in progress would leave this layout with, or null when it leaves it alone. */
const planned = $computed(() => drop.plan?.layouts[layoutId] ?? null)

// While a widget is in hand, the layout on screen is the one letting go would produce, putting
// the drop target where the widget will be.
const rows = $computed<WidgetRow[]>(() => {
  const plan = planned
  if (plan == null) {
    return layout
  }

  // Read from every layout since a widget arriving from another one is not in this one yet,
  // and from the drag itself since an insertion drag's widgets are in no layout at all.
  const widgets = new Map(
    workspace.layouts
      .flatMap((current) => current.rows)
      .flatMap((row) => row.widgets)
      .concat(workspace.drag?.widgets ?? [])
      .map((widget) => [widget.id, widget]),
  )
  const current = new Map(layout.map((row) => [row.id, row]))

  return plan.map((row) => {
    const contents = row.widgets.map((id) => widgets.get(id)).filter((widget) => widget != null)

    // Rows the move leaves alone keep the identity they already had so the widgets inside them
    // are not handed a fresh container on every pointer move.
    const unchanged = current.get(row.id) ?? null
    if (
      unchanged != null &&
      unchanged.height === row.height &&
      unchanged.collapsed === row.collapsed &&
      unchanged.widgets.length === contents.length &&
      unchanged.widgets.every((widget, index) => widget === contents[index])
    ) {
      return unchanged
    }

    return { id: row.id, height: row.height, collapsed: row.collapsed, widgets: contents }
  })
})

// The widget whose edge is being dragged. Every widget in that row shows its share while the
// drag lasts.
let resizing = $ref<Widget | null>(null)

/** The row whose bottom edge is being dragged, which shows its height while the drag lasts. */
let resizingRow = $ref<WidgetRow | null>(null)

// A collapsed row's height is auto, which cannot be animated closed. Pinning the height as the
// row leaves gives the collapse a starting point.
function pinRowHeight(target: Element) {
  const row = target as HTMLElement
  row.style.height = `${row.offsetHeight}px`
}

/** A widget's share of the row it is in, which a horizontal resize actually sets. */
function getWidgetShare(widget: Widget) {
  return `${Math.round((widget.width / widgetWidthSubdivisions) * 100)}%`
}

function isHeld(widget: Widget) {
  return drop.active && workspace.drag?.widgets.some((held) => held.id === widget.id) === true
}

// Expressed as a share of the row rather than pixels. Pixel widths overflow the row whenever the
// box changes size, as a carousel slide does when it gains a scrollbar.
function getWidgetWidthStyle(widget: Widget, isLast: boolean) {
  const units = drop.plan?.widths[widget.id] ?? widget.width
  const width = `${((units / widgetWidthSubdivisions) * 100).toFixed(4)}%`

  // The last widget has no ceiling so it absorbs the rounding remainder. It keeps a floor so a
  // widget arriving in the last place animates open rather than jumping to full size.
  return isLast ? { minWidth: width } : { maxWidth: width, minWidth: width }
}

/** Take a row to `height`, moving the surrounding box by the same amount where the row fills it.

A filling row's own height is not what renders so moving the box is what makes the drag visible.
*/
function setRowHeight(row: WidgetRow, index: number, height: number) {
  const change = height - row.height
  row.height = height

  if (host != null && isFilling(row, index)) {
    host.height = Math.max(shortestHost, host.height + change)
  }
}

function setWidgetWidth(row: WidgetRow, widget: Widget, column: number, pixels: number) {
  if (layoutWidth == null) {
    return
  }

  widget.width = Math.round((pixels / layoutWidth) * widgetWidthSubdivisions)
  resolveWidgetWidths(row.widgets, column, 'after')
}

/** Below this a carousel or a tab strip has no room left for the thing it is made of. */
const shortestHost = 80

/** Whether this row takes a share of the height left over. A collapsed row never does, being
already as short as it goes. */
function isFilling(row: WidgetRow, index: number) {
  if (expand === 'none' || row.collapsed) {
    return false
  }

  if (expand === 'even') {
    return true
  }

  return expand === 'first' ? index === 0 : index === rows.length - 1
}

const addWidgetItems = Object.values(widgetInfos).map((info) => ({
  label: info.name,
  onSelect: () => {
    workspace.addWidget(info.type, 0, 0, layoutId)
  },
}))

onMounted(() => {
  for (const row of layout) {
    resolveWidgetWidths(row.widgets)
  }
})

// The box the drop marker is placed against, and what the drag measures this layout by.
defineExpose({ element: $$(element) })
</script>

<template>
  <div ref="element" :class="[$style.root, shrink && $style.rootFitting]" data-layout>
    <!-- An empty layout offers the same add button the workspace carries under its own layout,
    since a widget can otherwise only arrive by drag. -->
    <div
      v-if="rows.length === 0"
      class="flex min-h-[120px] flex-auto flex-col items-center justify-center"
      @pointerdown="workspace.focusLayout(layoutId)"
    >
      <c-dropdown-menu :items="addWidgetItems">
        <c-tooltip text="Add Widget">
          <c-button aria-label="Add Widget" class="rounded-full" :icon="icons.add" size="xs" />
        </c-tooltip>
      </c-dropdown-menu>
    </div>
    <!-- Marks where the widget lands. Drawn only until the target has been held briefly so a
    pointer crossing the workspace does not rearrange everything it passes. -->
    <div
      v-if="drop.marker != null && drop.marker.layout === layoutId"
      :class="$style.dropMarker"
      :style="{
        left: `${drop.marker.left}px`,
        top: `${drop.marker.top}px`,
        width: `${drop.marker.width}px`,
        height: `${drop.marker.height}px`,
      }"
    />
    <!-- Rows slide to their new positions, which reads as movement rather than a redraw.
    Rendered under a tag of its own since move testing needs an element and a fragment has
    none. -->
    <transition-group
      :class="[
        $style.rows,
        expand !== 'none' && $style.rowsFilling,
        shrink && $style.rowsShrinking,
      ]"
      :enter-active-class="$style.rowEnterActive"
      :enter-from-class="$style.rowEnterFrom"
      :leave-active-class="drop.active ? undefined : $style.rowClosing"
      :leave-to-class="drop.active ? undefined : $style.rowClosed"
      :move-class="$style.rowMove"
      tag="div"
      @before-leave="pinRowHeight"
    >
      <div
        v-for="(row, i) in rows"
        :key="row.id"
        class="relative w-full"
        :class="isFilling(row, i) && $style.rowFilling"
        data-row
        :style="{
          height: row.collapsed ? undefined : `${row.height}px`,
        }"
      >
        <c-resize-handle
          v-if="!drop.active && !row.collapsed"
          class="absolute -bottom-[4.5px] left-0 z-[1]"
          direction="vertical"
          :min="
            Math.max(
              ...row.widgets.map((widget) => getWidgetInfo(widget.type).options.minHeight ?? 50),
              50,
            )
          "
          :model-value="row.height"
          :readout="false"
          :step="5"
          visibility="hover"
          @update:dragging="(dragging: boolean) => (resizingRow = dragging ? row : null)"
          @update:model-value="(value: number) => setRowHeight(row, i, value)"
        />
        <!-- A row is sized in pixels so its readout shows pixels where a widget's shows its
        share. -->
        <div v-if="resizingRow === row" :class="[$style.share, 'flex items-center justify-center']">
          <span :class="$style.shareValue">{{ Math.round(row.height) }}px</span>
        </div>
        <!-- The box the widgets are laid out across. Move measurement lays out a copy in here,
        and a boxless wrapper would land that copy among the widgets it is measuring. -->
        <transition-group
          class="flex h-full w-full flex-nowrap"
          :enter-active-class="$style.widgetOpening"
          :enter-from-class="$style.widgetClosed"
          :leave-active-class="drop.active ? undefined : $style.widgetOpening"
          :leave-to-class="drop.active ? undefined : $style.widgetClosed"
          tag="div"
        >
          <div
            v-for="(widget, j) in row.widgets"
            :key="widget.id"
            class="relative"
            :class="[
              j < row.widgets.length - 1 ? 'shrink' : 'grow',
              drop.active && $style.widgetResizing,
              row.widgets.length === 1
                ? ''
                : j === 0
                  ? 'pr-1'
                  : j === row.widgets.length - 1
                    ? 'pl-1'
                    : 'px-1',
            ]"
            data-widget
            :style="getWidgetWidthStyle(widget, j === row.widgets.length - 1)"
          >
            <c-resize-handle
              v-if="layoutWidth && !drop.active && j < row.widgets.length - 1"
              class="absolute -right-[0.5px] top-0 z-[1]"
              direction="horizontal"
              :min="100"
              :model-value="(widget.width / widgetWidthSubdivisions) * layoutWidth"
              :readout="false"
              :step="1 / widgetWidthSubdivisions"
              visibility="hover"
              @update:dragging="(dragging: boolean) => (resizing = dragging ? widget : null)"
              @update:model-value="(pixels: number) => setWidgetWidth(row, widget, j, pixels)"
            />
            <!-- Every widget in the row shows its share while one is being sized since giving
            one width takes it from the others. The one under the hand is highlighted. -->
            <div
              v-if="resizing != null && row.widgets.includes(resizing)"
              :class="[
                $style.share,
                'flex items-center justify-center',
                widget !== resizing && 'opacity-55',
              ]"
            >
              <span :class="$style.shareValue">{{ getWidgetShare(widget) }}</span>
            </div>
            <c-workspace-widget-placeholder v-if="isHeld(widget)" :widget="widget" />
            <c-workspace-widget
              v-else
              :column="j"
              :container="row"
              :layout-id="layoutId"
              :row="i"
              :widget="widget"
            />
          </div>
        </transition-group>
      </div>
    </transition-group>
  </div>
</template>

<style module>
/* Movement starts at once and comes to rest so the layout reads as settling. `--settle` is the
one knob for how long the layout takes after a change. */
.root {
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
  --settle: 240ms;
  --fade: 210ms;

  position: relative;
  min-height: 100%;

  /* A column so an empty layout can take its full height. The box also keeps the rows' margins
  inside it since escaping margins would make a filling layout taller than its container. */
  display: flex;
  flex-direction: column;
}

/* Row spacing lives here as a gap since margins between flex items do not collapse and would
double the spacing in a filling layout. */
.rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 0;
}

/* Rows span the layout's height so leftover height can be given to one of them. Only rows marked
as filling may take more. */
.rowsFilling {
  flex: 1 1 auto;
  min-height: 0;
}

.rows > * {
  flex: 0 0 auto;
}

/* Only the filling rows are squeezed so height taken from a slide comes out of the row taking
up the slack rather than out of all of them evenly. */
.rowsShrinking {
  min-height: 0;
}

.rowsShrinking > * {
  flex-shrink: 0;
}

/* Grows from the dragged height rather than replacing it so a filling row is never shorter than
it was asked to be. */
.rows > .rowFilling {
  flex: 1 1 auto;
  min-height: 0;
}

/* Fills and is capped at any definite height it is given. An empty slide then has a box to drop
onto, and a layout allowed to grow would scroll instead of squeezing its rows. */
.rootFitting {
  height: 100%;
  min-height: 0;
}

/* Drawn at the next target without animating between targets since a line sliding between
orientations would depict a change the layout is not making. */
.dropMarker {
  position: absolute;
  z-index: 2;
  border-radius: 2px;
  background-color: var(--ui-primary);
  pointer-events: none;
}

/* Laid over the widget, dimming it so the row reads as a set of shares. */
.share {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  background-color: #ffffff73;
}

:global(.dark) .share {
  background-color: #00000059;
}

/* On a chip of its own so the number stays legible over any widget content. */
.shareValue {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  background-color: #ffffffe6;
  color: #000000b3;
}

:global(.dark) .shareValue {
  background-color: #000000d9;
  color: #ffffffe6;
}

/* Only the position is animated. Heights arrive at once so the gap a drop opens is visible
immediately. */
.rowMove {
  transition: transform var(--settle) var(--ease-out);
}

/* A row arriving fades up while its neighbours slide apart, separating what is new from what
moved to make room. */
.rowEnterActive {
  transition: opacity var(--fade) ease-out;
}

.rowEnterFrom {
  opacity: 0;
}

/* A departing row closes, margins included, or the gap it sat in would remain. Disabled while a
widget is in hand, where a closing row is only the preview being rearranged. */
.rowClosing {
  overflow: hidden;
  transition:
    height var(--settle) var(--ease-out),
    margin var(--settle) var(--ease-out),
    opacity var(--fade) ease-out;
}

.rowClosed {
  height: 0 !important;
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  opacity: 0;
}

/* A widget joining or leaving a row opens and closes rather than appearing at its full width, so
the room it takes is seen being made for it. */
.widgetOpening {
  overflow: hidden;
  transition:
    min-width var(--settle) var(--ease-out),
    max-width var(--settle) var(--ease-out),
    opacity var(--settle) ease-out;
}

/* Overrides the widths set inline from the layout. The basis goes too, or a widget sizing from
its contents would open from its content width rather than from nothing. */
.widgetClosed {
  flex-basis: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  opacity: 0;
}

/* Only while a widget is in hand. A width that eases would fight the resize handle, which sets it
again on every pixel the pointer travels. */
.widgetResizing {
  transition:
    min-width var(--settle) var(--ease-out),
    max-width var(--settle) var(--ease-out);
}
</style>
