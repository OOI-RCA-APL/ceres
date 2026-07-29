import { useEventListener } from '@vueuse/core'
import { computed, reactive } from 'vue'

import {
  planWidgetsMove,
  resolveWidths,
  widgetWidthSubdivisions,
  WidgetPlacement,
  WidgetRow,
  WorkspaceContext,
} from '@/workspace'

/** Region-based drop targeting for the widgets of a workspace.

The gap between two rows opens a row of its own there. Inside a row, the outer third of a widget's
width drops in beside that widget, and the middle third is the one place with no target, which is
where a widget is let go of to leave the layout as it was.

A target is drawn as a line first and only opens the layout once it has been held, so a pointer
travelling across the workspace says where it is without rearranging everything it passes.

The layout a drop is measured against is the one with the held widget already taken out of it,
worked out once when the drag begins. Nothing is measured again after that, so the preview opening
under the pointer cannot shift the target the pointer is aiming at.
*/

/** How far the pointer travels before a press on a widget's header counts as a drag. */
const activationDistance = 5

/** How far outside the layout a drop still lands inside it. */
const edgeMargin = 40

/** How far past the first and last rows a drop still lands at the seam over or under them.

Every other seam is a gap with a row on each side to reach it from. Those two have a row on one
side only, so they are given the room the missing side would have offered and more, which makes
them no harder to drop into than the seams between rows.
*/
const outerReach = 96

/** How long a target is held before the layout opens for it.

Opening moves whatever the widget is arriving among, so a pointer travelling across several targets
would have the page rearranging under it the entire way. Until this elapses the target is drawn as
a line, which says where the widget lands without anything having to move for it, and the layout
only opens once the hand has settled on somewhere.
*/
const targetDwell = 600

/** How thick that line is drawn. */
const markerThickness = 3

type WidgetBounds = { left: number; right: number }

type RowBounds = { top: number; bottom: number; widgets: WidgetBounds[] }

/** Measure the rows and their widgets, relative to the box they are laid out in. */
function measure(element: HTMLElement): RowBounds[] {
  const origin = element.getBoundingClientRect()

  return [...element.querySelectorAll('[data-row]')].map((row) => {
    const bounds = row.getBoundingClientRect()

    return {
      top: bounds.top - origin.top,
      bottom: bounds.bottom - origin.top,
      widgets: [...row.querySelectorAll('[data-widget]')].map((widget) => {
        const cell = widget.getBoundingClientRect()

        return { left: cell.left - origin.left, right: cell.right - origin.left }
      }),
    }
  })
}

/** Adjust measurements to the layout that taking the held widgets out of it leaves behind. */
function withoutHeld(bounds: RowBounds[], layout: WidgetRow[], held: Set<string>): RowBounds[] {
  const remainder: RowBounds[] = []
  let risen = 0

  for (const [index, measured] of bounds.entries()) {
    const widgets = layout[index]?.widgets ?? []
    const remaining = widgets.filter((widget) => !held.has(widget.id))

    if (remaining.length === 0) {
      // The row goes with the widgets, and everything under it rises by the room that row took up.
      const below = bounds[index + 1] ?? null
      risen += below != null ? below.top - measured.top : 0
      continue
    }

    const top = measured.top - risen
    const bottom = measured.bottom - risen

    if (remaining.length === widgets.length) {
      remainder.push({ top, bottom, widgets: measured.widgets })
      continue
    }

    // The widgets left in the row spread across the width the held ones give up.
    const resolved = resolveWidths(remaining.map((widget) => widget.width))
    const left = measured.widgets[0].left
    const right = measured.widgets[measured.widgets.length - 1].right

    let x = left
    const cells = resolved.map((units) => {
      const cell = { left: x, right: x + ((right - left) * units) / widgetWidthSubdivisions }
      x = cell.right

      return cell
    })

    if (cells.length > 0) {
      cells[cells.length - 1].right = right
    }

    remainder.push({ top, bottom, widgets: cells })
  }

  return remainder
}

function resolveColumn(row: RowBounds, index: number, x: number): WidgetPlacement | null {
  const widgets = row.widgets
  const first = widgets[0] ?? null
  const last = widgets[widgets.length - 1] ?? null
  if (first == null || last == null) {
    return null
  }
  if (x <= first.left) {
    return { row: index, column: 0 }
  }
  if (x >= last.right) {
    return { row: index, column: widgets.length }
  }

  for (const [column, widget] of widgets.entries()) {
    if (x > widget.right) {
      continue
    }

    // Between two widgets, which is the same seam whichever side it is approached from.
    if (x < widget.left) {
      return { row: index, column }
    }

    const third = (widget.right - widget.left) / 3
    if (x < widget.left + third) {
      return { row: index, column }
    }
    if (x > widget.right - third) {
      return { row: index, column: column + 1 }
    }

    return null
  }

  return null
}

/** Where a seam sits, halfway across the gap the rows leave between them. */
function seamOf(bounds: RowBounds[], row: number): number | null {
  const above = bounds[row - 1] ?? null
  const below = bounds[row] ?? null

  if (above != null && below != null) {
    return (above.bottom + below.top) / 2
  }
  if (below != null) {
    return below.top - 4
  }
  if (above != null) {
    return above.bottom + 4
  }

  return null
}

/** The line drawn where a widget lands, before the layout opens to take it. */
export type DropMarker = { left: number; top: number; width: number; height: number }

/** Work out where that line goes, across a seam or down between two widgets in a row. */
function markerOf(
  bounds: RowBounds[],
  width: number,
  placement: WidgetPlacement
): DropMarker | null {
  if (placement.column == null) {
    const y = seamOf(bounds, placement.row)

    return y == null
      ? null
      : { left: 0, top: y - markerThickness / 2, width, height: markerThickness }
  }

  const row = bounds[placement.row] ?? null
  if (row == null) {
    return null
  }

  // Between the widgets it is going between, and against the outer edge at either end of the row.
  const before = row.widgets[placement.column - 1] ?? null
  const after = row.widgets[placement.column] ?? null
  const x =
    before != null && after != null
      ? (before.right + after.left) / 2
      : after?.left ?? before?.right ?? null
  if (x == null) {
    return null
  }

  return {
    left: x - markerThickness / 2,
    top: row.top,
    width: markerThickness,
    height: row.bottom - row.top,
  }
}

function samePlacement(one: WidgetPlacement | null, other: WidgetPlacement | null): boolean {
  if (one == null || other == null) {
    return one === other
  }

  return one.row === other.row && one.column === other.column
}

function resolvePlacement(
  bounds: RowBounds[],
  width: number,
  x: number,
  y: number
): WidgetPlacement | null {
  const first = bounds[0] ?? null
  const last = bounds[bounds.length - 1] ?? null
  if (first == null || last == null) {
    return null
  }
  if (x < -edgeMargin || x > width + edgeMargin) {
    return null
  }
  if (y < first.top - outerReach || y > last.bottom + outerReach) {
    return null
  }

  // A seam is the gap between two rows and nothing more. A widget is taken hold of by its header,
  // which sits at the very top of it, so a seam claiming any of a row's own height would be chosen
  // before the pointer had travelled at all. Opening a row means reaching the gap it goes in,
  // which is a thing the hand has to mean to do, and the rest of a row is for dropping beside the
  // widgets in it.
  for (const [index, row] of bounds.entries()) {
    if (y < row.top) {
      return { row: index, column: null }
    }
    if (y <= row.bottom) {
      return resolveColumn(row, index, x)
    }
  }

  return { row: bounds.length, column: null }
}

export function useWidgetDrop(workspace: WorkspaceContext, container: () => HTMLElement | null) {
  let bounds: RowBounds[] = []
  let width = 0
  let origin: { x: number; y: number } | null = null
  let begun = false

  let active = $ref(false)
  let placement = $ref<WidgetPlacement | null>(null)

  // Whether the layout has opened for the placement, which every target earns the same way, by
  // being held rather than only passed over.
  let opened = $ref(false)
  let marker = $ref<DropMarker | null>(null)
  let dwell: ReturnType<typeof setTimeout> | null = null

  function hold(chosen: WidgetPlacement | null) {
    placement = chosen

    if (dwell != null) {
      clearTimeout(dwell)
      dwell = null
    }

    opened = chosen == null
    marker = chosen == null ? null : markerOf(bounds, width, chosen)

    if (!opened) {
      dwell = setTimeout(() => {
        opened = true
        marker = null
        dwell = null
      }, targetDwell)
    }
  }

  function reset() {
    if (dwell != null) {
      clearTimeout(dwell)
      dwell = null
    }

    bounds = []
    width = 0
    origin = null
    begun = false
    active = false
    placement = null
    opened = false
    marker = null
  }

  function begin(): boolean {
    begun = true

    const element = container()
    const data = workspace.data
    const drag = workspace.drag
    if (element == null || data == null || drag == null) {
      return false
    }

    // Holding everything the workspace has leaves nothing on the page to aim at, and nowhere for
    // any of it to go.
    const total = data.layout.reduce((count, row) => count + row.widgets.length, 0)
    if (total - drag.widgets.length < 1) {
      return false
    }

    const held = new Set(drag.widgets.map((widget) => widget.id))
    bounds = withoutHeld(measure(element), data.layout, held)
    width = element.clientWidth
    active = true

    return true
  }

  function release() {
    const drag = workspace.drag
    if (drag != null) {
      if (active && placement != null) {
        workspace.moveWidgets(
          drag.widgets.map((widget) => widget.id),
          placement
        )
      } else if (!active) {
        // A press that never travelled is a plain click, which narrows what is picked out to the
        // widget under it rather than leaving the rest of a selection standing.
        workspace.selectWidget(drag.widget.id)
      }

      workspace.drag = null
    }

    reset()
  }

  function cancel() {
    hold(null)
    release()
  }

  // Where the press landed, taken before the widget's own handler decides whether it starts a
  // drag, so the distance travelled is measured from the press rather than from the first move.
  useEventListener(window, 'pointerdown', (event: PointerEvent) => {
    origin = { x: event.clientX, y: event.clientY }

    // Pressing anywhere but on a widget lets go of what is picked out, the way clicking off a
    // selection does elsewhere. Overlays are exempt, since a menu or dialog is usually acting on
    // the selection rather than leaving it.
    const target = event.target as HTMLElement | null
    if (
      workspace.selection.length > 0 &&
      target?.closest('[data-widget], .q-menu, .q-dialog, .q-popup-edit') == null
    ) {
      workspace.clearSelection()
    }
  })

  useEventListener(window, 'pointermove', (event: PointerEvent) => {
    if (workspace.drag == null) {
      return
    }

    if (!active) {
      if (begun) {
        return
      }

      origin ??= { x: event.clientX, y: event.clientY }
      if (Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < activationDistance) {
        return
      }
      if (!begin()) {
        return
      }
    }

    const element = container()
    if (element == null) {
      return
    }

    // The box is read again each time, so a page that scrolls under the pointer still places it
    // against the same measurements.
    const box = element.getBoundingClientRect()
    const resolved = resolvePlacement(
      bounds,
      width,
      event.clientX - box.left,
      event.clientY - box.top
    )

    // Held only when it names somewhere else. Every move resolves a target of its own, so handing
    // one over that says what the last one said would rebuild the preview and set the rows moving
    // again on every frame the pointer travels, rather than once as it crosses into somewhere new.
    if (!samePlacement(resolved, placement)) {
      hold(resolved)
    }
  })

  useEventListener(window, 'pointerup', release)
  useEventListener(window, 'pointercancel', cancel)

  // A safety net for anything that gets as far as a press without the pointer events that follow
  // it, which would otherwise leave a widget stuck to the cursor.
  useEventListener(window, 'mouseup', release)

  // Escape backs out of whichever is in progress, a drag first and then the selection behind it.
  useEventListener(window, 'keydown', (event: KeyboardEvent) => {
    if (event.key !== 'Escape') {
      return
    }

    if (workspace.drag != null) {
      cancel()
    } else {
      workspace.clearSelection()
    }
  })

  const plan = $computed(() => {
    const drag = workspace.drag
    if (!active || drag == null || workspace.data == null) {
      return null
    }

    return planWidgetsMove(
      workspace.data.layout,
      drag.widgets.map((widget) => widget.id),
      opened ? placement : null
    )
  })

  return reactive({
    /** Whether a press has travelled far enough to be a drag. */
    active: computed(() => active),

    /** Where the held widget would land, or null while it is over nowhere in particular. */
    placement: computed(() => placement),

    /** The layout letting go right now would produce, to draw in place of the current one. */
    plan: computed(() => plan),

    /** The line saying where the widget lands, until the layout opens for it. Layout-relative. */
    marker: computed(() => marker),
  })
}
