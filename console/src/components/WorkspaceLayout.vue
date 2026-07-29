<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { onMounted } from 'vue'

import ResizeHandle from '@/components/ResizeHandle.vue'
import WorkspaceWidget from '@/components/WorkspaceWidget.vue'
import WorkspaceWidgetPlaceholder from '@/components/WorkspaceWidgetPlaceholder.vue'
import { WidgetDrop } from '@/widget-drop'
import {
  getWidgetInfo,
  resolveWidgetWidths,
  useWorkspace,
  widgetWidthSubdivisions,
  Widget,
  WidgetRow,
} from '@/workspace'

const { drop, layout } = defineProps<{
  /** The rows this editor arranges. Written in place, so it is the layout itself. */
  layout: WidgetRow[]

  /** The drag in progress, which says where a widget would land in here. */
  drop: WidgetDrop
}>()

const workspace = useWorkspace()

const element = $ref<HTMLDivElement | null>(null)
let layoutWidth = $ref<number | null>(null)

useResizeObserver($$(element), (resizes) => {
  for (const resize of resizes) {
    layoutWidth = resize.contentRect.width
  }
})

// While a widget is in hand the layout on screen is the one letting go would produce, which puts
// the drop target where the widget itself will be rather than beside a mark standing in for it.
const rows = $computed<WidgetRow[]>(() => {
  if (drop.plan == null) {
    return layout
  }

  const widgets = new Map(layout.flatMap((row) => row.widgets).map((widget) => [widget.id, widget]))
  const current = new Map(layout.map((row) => [row.id, row]))

  return drop.plan.rows.map((row) => {
    const contents = row.widgets.map((id) => widgets.get(id)).filter((widget) => widget != null)

    // Rows the move leaves alone keep the identity they already had, so the widgets inside them
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

// The widget whose edge is being dragged, while it is being dragged. Every widget in that row is
// resized by it, so the whole row says its share for as long as it lasts.
let resizing = $ref<Widget | null>(null)

/** The row whose bottom edge is being dragged, which says its height for as long as it lasts. */
let resizingRow = $ref<WidgetRow | null>(null)

// A collapsed row is as tall as it needs to be rather than a number of pixels, and there is no
// closing a height of auto. Taking the height it has as it leaves gives the collapse somewhere to
// start from, whichever kind of row it is.
function pinRowHeight(target: Element) {
  const row = target as HTMLElement
  row.style.height = `${row.offsetHeight}px`
}

/** A widget's share of the row it is in, which is what a horizontal resize actually sets. */
function getWidgetShare(widget: Widget) {
  return `${Math.round((widget.width / widgetWidthSubdivisions) * 100)}%`
}

function isHeld(widget: Widget) {
  return drop.active && workspace.drag?.widgets.some((held) => held.id === widget.id) === true
}

function getWidgetWidthStyle(widget: Widget, isLast: boolean) {
  if (layoutWidth == null) {
    return undefined
  }

  const units = drop.plan?.widths[widget.id] ?? widget.width
  const width = `${Math.round((units / widgetWidthSubdivisions) * layoutWidth).toFixed(1)}px`

  // The last widget in a row is left without a ceiling, so it takes up whatever the rounding leaves
  // over. A ceiling of none is not a width anything can be animated from, so a widget arriving in
  // the last place is given a floor to open out to instead of jumping straight to its full size.
  return isLast ? { minWidth: width } : { maxWidth: width, minWidth: width }
}

onMounted(() => {
  for (const row of layout) {
    resolveWidgetWidths(row.widgets)
  }
})

// The box the drop marker is placed against, and what the drag measures this layout by.
defineExpose({ element: $$(element) })
</script>

<template>
  <div ref="element" :class="$style.root">
    <!-- Where the widget lands, said without the layout having to open for it. Drawn until the
    target has been held long enough to be meant, so a pointer travelling across the workspace
    does not rearrange everything it passes over on the way. -->
    <div
      v-if="drop.marker != null"
      :class="$style.dropMarker"
      :style="{
        left: `${drop.marker.left}px`,
        top: `${drop.marker.top}px`,
        width: `${drop.marker.width}px`,
        height: `${drop.marker.height}px`,
      }"
    />
    <!-- Rows slide to wherever a change puts them instead of arriving there outright, which is
    what makes a gap opening somewhere legible as these rows moving down rather than as the page
    having been redrawn. Rendered under a tag of its own, since working out whether a row can be
    moved at all needs an element to test against and a fragment has none. -->
    <transition-group
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
        class="full-width q-my-sm relative-position"
        data-row
        :style="{
          height: row.collapsed ? undefined : `${row.height}px`,
        }"
      >
        <resize-handle
          v-if="!drop.active && !row.collapsed"
          v-model="row.height"
          :class="$style.verticalResizeHandle"
          direction="vertical"
          :min="
            Math.max(
              ...row.widgets.map((widget) => getWidgetInfo(widget.type).options.minHeight ?? 50),
              50
            )
          "
          :readout="false"
          :step="5"
          visibility="hover"
          @update:dragging="(dragging: boolean) => (resizingRow = dragging ? row : null)"
        />
        <!-- A row is sized in pixels rather than in shares of anything, so its height is what
        it says, laid over the row the same way each widget says its share of one. -->
        <div
          v-if="resizingRow === row"
          :class="[$style.share, 'items-center', 'justify-center', 'row']"
        >
          <span :class="$style.shareValue">{{ Math.round(row.height) }}px</span>
        </div>
        <!-- The box the widgets are laid out across, rather than a boxless wrapper inside it.
        Working out whether a widget can be moved measures a copy of one laid out in here, and a
        wrapper that generates no box of its own has that copy landing among the widgets it is
        measuring, which leaves them holding the offsets it worked out. -->
        <transition-group
          class="full-height full-width no-wrap row"
          :enter-active-class="$style.widgetOpening"
          :enter-from-class="$style.widgetClosed"
          :leave-active-class="drop.active ? undefined : $style.widgetOpening"
          :leave-to-class="drop.active ? undefined : $style.widgetClosed"
          tag="div"
        >
          <div
            v-for="(widget, j) in row.widgets"
            :key="widget.id"
            :class="[
              j < row.widgets.length - 1 ? 'col-shrink' : 'col-grow',
              'relative-position',
              drop.active && $style.widgetResizing,
              row.widgets.length === 1
                ? ''
                : j === 0
                ? 'q-pr-xs'
                : j === row.widgets.length - 1
                ? 'q-pl-xs'
                : 'q-px-xs',
            ]"
            data-widget
            :style="getWidgetWidthStyle(widget, j === row.widgets.length - 1)"
          >
            <resize-handle
              v-if="layoutWidth && !drop.active && j < row.widgets.length - 1"
              :class="$style.horizontalResizeHandle"
              direction="horizontal"
              :min="100"
              :model-value="(widget.width / widgetWidthSubdivisions) * layoutWidth"
              :readout="false"
              :step="1 / widgetWidthSubdivisions"
              visibility="hover"
              @update:dragging="(dragging: boolean) => (resizing = dragging ? widget : null)"
              @update:model-value="
                (pixels) => {
                  if (layoutWidth == null) {
                    return
                  }

                  widget.width = Math.round((pixels / layoutWidth) * widgetWidthSubdivisions)
                  resolveWidgetWidths(row.widgets, j, 'after')
                }
              "
            />
            <!-- Every widget in the row says its share while one of them is being sized, since
            giving one width takes it from the others. The one under the hand is the one being
            answered for, so the rest are said quietly. -->
            <div
              v-if="resizing != null && row.widgets.includes(resizing)"
              :class="[
                $style.share,
                'items-center',
                'justify-center',
                'row',
                widget !== resizing && $style.shareQuiet,
              ]"
            >
              <span :class="$style.shareValue">{{ getWidgetShare(widget) }}</span>
            </div>
            <workspace-widget-placeholder v-if="isHeld(widget)" :widget="widget" />
            <workspace-widget v-else :column="j" :container="row" :row="i" :widget="widget" />
          </div>
        </transition-group>
      </div>
    </transition-group>
  </div>
</template>

<style lang="scss" module>
// Movement starts at once and comes to rest, which reads as the layout settling rather than as
// something being played back at it.
$easeOut: cubic-bezier(0.2, 0, 0, 1);

// How long the layout takes to settle after a change, and the one knob for all of it. Long enough
// to be followed rather than only noticed, and short enough to keep up with a pointer still moving.
$settle: 240ms;
$fade: 210ms;

// What the drop marker is placed against.
.root {
  position: relative;
}

// Drawn where the next target is and nowhere in between. Travelling there would have a line lying
// along a seam turning into one standing between two widgets, which is not a thing happening to
// the layout. It runs either way, so the box it is given rather than a fixed side decides which.
.dropMarker {
  position: absolute;
  z-index: 2;
  border-radius: 2px;
  background-color: $primary;
  pointer-events: none;
}

// Laid over the widget rather than beside it, so the number sits on the thing it is the width of
// and the widget behind is dimmed to leave the row reading as a set of shares.
.share {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

// Carried on a chip of its own, so the number stays legible over whatever the widget happens to be
// showing rather than relying on the wash over it to hide it.
.shareValue {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.shareQuiet {
  opacity: 0.55;
}

:global(.dark) .share {
  background-color: #00000059;
}

:global(.dark) .shareValue {
  background-color: #000000d9;
  color: #ffffffe6;
}

:global(.light) .share {
  background-color: #ffffff73;
}

:global(.light) .shareValue {
  background-color: #ffffffe6;
  color: #000000b3;
}

.verticalResizeHandle {
  position: absolute;
  left: 0px;
  bottom: -4.5px;
  z-index: 1;
}

.horizontalResizeHandle {
  position: absolute;
  right: -0.5px;
  top: 0px;
  z-index: 1;
}

// Rows travel to wherever a change puts them. Short enough to keep up with a pointer that is still
// moving, and eased so the movement reads as one thing settling rather than everything restarting.
// Only the position is animated. A row's height arrives at once, so the gap a drop opens is there
// to see straight away and only the rows giving way to it are in motion.
.rowMove {
  transition: transform $settle $easeOut;
}

// A row arriving fades up while the rows around it slide apart, which separates the thing that is
// new from the things that moved to make room for it.
.rowEnterActive {
  transition: opacity $fade ease-out;
}

.rowEnterFrom {
  opacity: 0;
}

// A row that goes closes rather than vanishing, and everything under it rises as the room it took
// up gives way. Its margins go with its height, or the gap it sat in would be left behind. Held
// off while a widget is in hand, where a row closing is the preview being rearranged rather than
// anything actually leaving.
.rowClosing {
  overflow: hidden;
  transition: height $settle $easeOut, margin $settle $easeOut, opacity $fade ease-out;
}

.rowClosed {
  height: 0 !important;
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  opacity: 0;
}

// A widget joining or leaving a row opens and closes rather than appearing at its full width, so
// the room it takes is seen being made for it.
.widgetOpening {
  overflow: hidden;
  transition: min-width $settle $easeOut, max-width $settle $easeOut, opacity $settle ease-out;
}

// Beats the widths set inline from the layout, which is where a widget's own width comes from. The
// basis goes with them, since a widget left free to size itself from its contents opens at whatever
// it happens to hold rather than from nothing.
.widgetClosed {
  flex-basis: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  opacity: 0;
}

// Only while a widget is in hand. A width that eases would fight the resize handle, which sets it
// again on every pixel the pointer travels.
.widgetResizing {
  transition: min-width $settle $easeOut, max-width $settle $easeOut;
}
</style>
