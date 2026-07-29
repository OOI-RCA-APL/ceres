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

Every point over the layout belongs to a target, and each one is large enough to hit without
aiming. A quarter of a row's height at its top and at its bottom opens a new row at that seam, so
the seam between two rows is as broad as a quarter of each of them. Across the half of a row's
height left in the middle, the outer third of a widget's width drops in beside that widget. The
middle third is the one place with no target, which is where a widget is let go of to leave the
layout as it was.

The layout a drop is measured against is the one with the held widget already taken out of it,
worked out once when the drag begins. Nothing is measured again after that, so the preview opening
under the pointer cannot shift the target the pointer is aiming at.
*/

/** How far the pointer travels before a press on a widget's header counts as a drag. */
const activationDistance = 5

/** How far outside the layout a drop still lands inside it. */
const edgeMargin = 40

/** The least a row gives up to the seams either side of it, for rows too short to spare a
quarter. */
const leastBand = 10

/** The most a row gives up to them, however tall it is.

A quarter alone reads as a seam being greedy on a tall row, where it would swallow half the row and
leave a drop beside the widget hard to reach. Past this the seam is a band of its own rather than a
share of anything, which also makes every seam the same size to aim at.
*/
const largestBand = 28

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

/** How much of a row's height belongs to the seams above and below it. */
function bandOf(row: RowBounds): number {
  const height = row.bottom - row.top

  return Math.min(Math.max(height / 4, leastBand), largestBand, height / 2)
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
  if (y < first.top - edgeMargin || y > last.bottom + edgeMargin) {
    return null
  }

  for (const [index, row] of bounds.entries()) {
    const band = bandOf(row)
    if (y < row.top + band) {
      return { row: index, column: null }
    }

    if (y > row.bottom - band) {
      const below = bounds[index + 1] ?? null
      const seam = below != null ? below.top + bandOf(below) : Infinity
      if (y < seam) {
        return { row: index + 1, column: null }
      }

      continue
    }

    return resolveColumn(row, index, x)
  }

  return null
}

export function useWidgetDrop(workspace: WorkspaceContext, container: () => HTMLElement | null) {
  let bounds: RowBounds[] = []
  let width = 0
  let origin: { x: number; y: number } | null = null
  let begun = false

  let active = $ref(false)
  let placement = $ref<WidgetPlacement | null>(null)

  function reset() {
    bounds = []
    width = 0
    origin = null
    begun = false
    active = false
    placement = null
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
    placement = null
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
      placement = resolved
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
      placement
    )
  })

  return reactive({
    /** Whether a press has travelled far enough to be a drag. */
    active: computed(() => active),

    /** Where the held widget would land, or null while it is over nowhere in particular. */
    placement: computed(() => placement),

    /** The layout letting go right now would produce, to draw in place of the current one. */
    plan: computed(() => plan),
  })
}
