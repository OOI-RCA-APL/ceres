import { useEventListener } from '@vueuse/core'
import { computed, inject, onScopeDispose, provide, reactive } from 'vue'

import { widgetDropInjectionKey } from '@/symbols'
import {
  layoutsWithin,
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

A workspace has more than one layout to aim at, since every carousel slide on screen is arranged
the same way the workspace is. Each one on screen registers itself, and the pointer is answered for
by the innermost it is over, so a widget is dragged into a slide and back out again in one motion.

The layouts a drop is measured against are the ones with the held widget already taken out, worked
out once when the drag begins. Nothing is measured again after that, so the preview opening under
the pointer cannot shift the target the pointer is aiming at.
*/

/** How far the pointer travels before a press on a widget's header counts as a drag. */
const activationDistance = 5

/** How far outside the layout a drop still lands inside it. */
const edgeMargin = 40

/** How far past the first and last rows a drop still lands at the seam over or under them.

Every other seam is a gap with a row on each side to reach it from, and overshooting one lands in
the row beyond it. These two have nothing beyond them to overshoot into, so all the empty page over
the first row and under the last belongs to them, and a row can be opened at either end without
having to find a gap at all.
*/
const outerReach = 240

/** How long a target is held before the layout opens for it.

Opening moves whatever the widget is arriving among, so a pointer travelling across several targets
would have the page rearranging under it the entire way. Until this elapses the target is drawn as
a line, which says where the widget lands without anything having to move for it, and the layout
only opens once the hand has settled on somewhere.
*/
const targetDwell = 300

/** How thick that line is drawn. */
const markerThickness = 3

/** The most of its own height a row gives up to the seams either side of it.

The gap between two rows is a few pixels of nothing, which is a hard thing to land a pointer on, so
each row lends the seams beside it some of its own edge. Waiting a target out before the layout
opens for it is what makes this affordable, since reaching over a seam on the way somewhere else
costs a line being drawn and nothing more.
*/
const largestBand = 48

type WidgetBounds = { left: number; right: number }

type RowBounds = { top: number; bottom: number; widgets: WidgetBounds[] }

/** Measure the rows and their widgets, relative to the box they are laid out in.

Only what this layout lays out itself. A carousel on one of its rows holds layouts of its own, and
their rows and widgets sit inside these ones while belonging to them rather than here.
*/
function measure(element: HTMLElement): RowBounds[] {
  const origin = element.getBoundingClientRect()
  const rows = [...element.querySelectorAll('[data-row]')].filter(
    (row) => row.closest('[data-layout]') === element
  )

  return rows.map((row) => {
    const bounds = row.getBoundingClientRect()

    return {
      top: bounds.top - origin.top,
      bottom: bounds.bottom - origin.top,
      widgets: [...row.querySelectorAll('[data-widget]')]
        .filter((widget) => widget.closest('[data-row]') === row)
        .map((widget) => {
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

/** Where a placement sits, before it is told which layout it belongs to. */
type Target = Omit<WidgetPlacement, 'layout'>

function resolveColumn(row: RowBounds, index: number, x: number): Target | null {
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

/** How much of a row's height belongs to the seams above and below it.

Never more than a third, so however short a row is there is always a middle left over to drop
beside the widgets in it.
*/
function bandOf(row: RowBounds): number {
  const height = row.bottom - row.top

  return Math.min(largestBand, height / 3)
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

/** The line drawn where a widget lands, before the layout opens to take it.

Placed against the layout it names, since the layouts on screen are nested and a line drawn in one
means nothing measured against another.
*/
export type DropMarker = {
  layout: string
  left: number
  top: number
  width: number
  height: number
}

/** Work out where that line goes, across a seam or down between two widgets in a row. */
function markerOf(
  bounds: RowBounds[],
  width: number,
  placement: WidgetPlacement
): DropMarker | null {
  const layout = placement.layout

  if (placement.column == null) {
    const y = seamOf(bounds, placement.row)

    return y == null
      ? null
      : { layout, left: 0, top: y - markerThickness / 2, width, height: markerThickness }
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
    layout,
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

  return one.layout === other.layout && one.row === other.row && one.column === other.column
}

function resolveTarget(bounds: RowBounds[], width: number, x: number, y: number): Target | null {
  const first = bounds[0] ?? null
  const last = bounds[bounds.length - 1] ?? null

  // A layout with nothing left in it is all one target, since there are no rows to aim between and
  // an empty carousel slide has to be reachable before anything can be put on it.
  if (first == null || last == null) {
    return { row: 0, column: null }
  }
  if (x < -edgeMargin || x > width + edgeMargin) {
    return null
  }
  if (y < first.top - outerReach || y > last.bottom + outerReach) {
    return null
  }

  // A seam reaches into the rows either side of it as well as across the gap between them, so it
  // is a band to aim at rather than a line. What is left in the middle of a row is for dropping
  // beside the widgets in it.
  for (const [index, row] of bounds.entries()) {
    const band = bandOf(row)
    if (y < row.top + band) {
      return { row: index, column: null }
    }

    // Already past this row and into the next one's own middle, so the seam between them is behind
    // the pointer and the next row answers for where it is.
    const below = bounds[index + 1] ?? null
    if (below != null && y >= below.top + bandOf(below)) {
      continue
    }

    if (y > row.bottom - band) {
      return { row: index + 1, column: null }
    }

    return resolveColumn(row, index, x)
  }

  return { row: bounds.length, column: null }
}

/** A layout on screen, which a drag may aim at for as long as it stays there. */
export type LayoutRegistration = {
  id: string
  rows: () => WidgetRow[]
  element: () => HTMLElement | null
}

/** A layout as a drag holds it, measured once and left alone for the rest of the drag. */
type MeasuredLayout = {
  id: string
  element: HTMLElement
  bounds: RowBounds[]
  width: number

  /** How deep in the page it sits, so the innermost layout under the pointer answers for it. */
  depth: number
}

function depthOf(element: HTMLElement): number {
  let depth = 0
  for (let parent = element.parentElement; parent != null; parent = parent.parentElement) {
    depth++
  }

  return depth
}

/** A drag in progress, as the layouts it is measured against read it. */
export type WidgetDrop = ReturnType<typeof createWidgetDrop>

function createWidgetDrop(workspace: WorkspaceContext) {
  const registered = new Map<string, LayoutRegistration>()

  let measured: MeasuredLayout[] = []
  let origin: { x: number; y: number } | null = null
  let begun = false

  let active = $ref(false)
  let placement = $ref<WidgetPlacement | null>(null)

  // Whether the layout has opened for the placement, which every target earns the same way, by
  // being held rather than only passed over.
  let opened = $ref(false)
  let marker = $ref<DropMarker | null>(null)
  let dwell: ReturnType<typeof setTimeout> | null = null

  /** Put a layout on screen up as a target, until whatever drew it goes away. */
  function register(registration: LayoutRegistration) {
    registered.set(registration.id, registration)
    onScopeDispose(() => {
      if (registered.get(registration.id) === registration) {
        registered.delete(registration.id)
      }
    })
  }

  function hold(chosen: WidgetPlacement | null) {
    placement = chosen

    if (dwell != null) {
      clearTimeout(dwell)
      dwell = null
    }

    opened = chosen == null
    const layout = chosen == null ? null : measured.find((entry) => entry.id === chosen.layout)
    marker = layout == null || chosen == null ? null : markerOf(layout.bounds, layout.width, chosen)

    if (!opened) {
      dwell = setTimeout(() => {
        opened = true
        marker = null
        dwell = null
      }, targetDwell)
    }
  }

  /** The layout drawn under a point, or the outermost one when the point is off all of them.

  Read from the page rather than from the measured boxes, so a layout that its surroundings clip
  claims only the part of itself that is actually on screen. Everywhere else belongs to the
  outermost layout, which is what carries the margins letting a drop land just off the edge of a
  workspace.
  */
  function claimant(x: number, y: number): MeasuredLayout | null {
    const outermost = measured[measured.length - 1] ?? null

    for (
      let element = document.elementFromPoint(x, y);
      element != null;
      element = element.parentElement
    ) {
      const layout = measured.find((candidate) => candidate.element === element) ?? null
      if (layout != null) {
        return layout
      }
    }

    return outermost
  }

  function reset() {
    if (dwell != null) {
      clearTimeout(dwell)
      dwell = null
    }

    measured = []
    origin = null
    begun = false
    active = false
    placement = null
    opened = false
    marker = null
  }

  function begin(): boolean {
    begun = true

    const drag = workspace.drag
    if (drag == null) {
      return false
    }

    const held = new Set(drag.widgets.map((widget) => widget.id))

    // A carousel in hand carries its own slides with it, and those are no place to put it down.
    // Left out here rather than refused on release, so nothing ever offers to take it.
    const carried = layoutsWithin(drag.widgets)

    // Only the layout the widgets are leaving closes up behind them. Every other one on screen
    // stays exactly where it is, so its measurements stand as they were taken.
    measured = [...registered.values()].flatMap((registration) => {
      const element = registration.element()
      if (element == null || carried.has(registration.id)) {
        return []
      }

      const rows = registration.rows()
      const holds = rows.some((row) => row.widgets.some((widget) => held.has(widget.id)))

      return [
        {
          id: registration.id,
          element,
          bounds: holds ? withoutHeld(measure(element), rows, held) : measure(element),
          width: element.clientWidth,
          depth: depthOf(element),
        },
      ]
    })

    if (measured.length === 0) {
      return false
    }

    // Innermost first, since a carousel slide sits inside the layout holding the carousel and is
    // the one being aimed at whenever the pointer is over it.
    measured.sort((one, other) => other.depth - one.depth)
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
        // widget under it rather than leaving the rest of a selection standing. Named with the
        // layout it was pressed in, or picking one out inside a carousel slide would be read as
        // reaching back out into the workspace and let go of again on the way up.
        workspace.selectWidget(drag.widget.id, 'replace', drag.layout)
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

    // Pressing anywhere but a widget's header lets go of what is picked out, the way clicking off
    // a selection does elsewhere. A press inside a widget is reaching for what the widget shows
    // rather than for the widget itself, so it counts as pressing away from the selection.
    //
    // A held modifier is exempt, since that press is being aimed at the selection rather than away
    // from it, as are overlays, where a menu or dialog is usually acting on what is picked out.
    const target = event.target as HTMLElement | null
    if (
      workspace.selection.length > 0 &&
      event.button === 0 &&
      !event.shiftKey &&
      !event.metaKey &&
      !event.ctrlKey &&
      target?.closest('[data-widget-header], .q-menu, .q-dialog, .q-popup-edit') == null
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

    // Whichever layout is actually drawn under the pointer answers for it, asked of the page
    // rather than worked out from boxes. A carousel scrolls its slide, so a slide taller than the
    // carousel showing it has a box reaching down over rows of the workspace that are nothing to
    // do with it, and only the page knows where it was really clipped.
    const inside = claimant(event.clientX, event.clientY)
    if (inside == null) {
      return
    }

    // The box is read again each time, so a page that scrolls under the pointer still places it
    // against the same measurements.
    const box = inside.element.getBoundingClientRect()
    const target = resolveTarget(
      inside.bounds,
      inside.width,
      event.clientX - box.left,
      event.clientY - box.top
    )
    const resolved = target == null ? null : { layout: inside.id, ...target }

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
    if (!active || drag == null) {
      return null
    }

    return planWidgetsMove(
      new Map(workspace.layouts.map((layout) => [layout.id, layout.rows])),
      drag.widgets.map((widget) => widget.id),
      opened ? placement : null
    )
  })

  return reactive({
    register,

    /** Whether a press has travelled far enough to be a drag. */
    active: computed(() => active),

    /** Where the held widget would land, or null while it is over nowhere in particular. */
    placement: computed(() => placement),

    /** The rows each layout the drop touches would settle on, to draw in place of its own. */
    plan: computed(() => plan),

    /** The line saying where the widget lands, until the layout opens for it. Layout-relative. */
    marker: computed(() => marker),
  })
}

/** Start a workspace's drag handling, and hand it to every layout drawn under this one. */
export function provideWidgetDrop(workspace: WorkspaceContext): WidgetDrop {
  const drop = createWidgetDrop(workspace)
  provide(widgetDropInjectionKey, drop)

  return drop
}

export function useWidgetDrop(): WidgetDrop {
  const drop = inject(widgetDropInjectionKey)
  if (drop == null) {
    throw new Error('Widget drop context not found.')
  }

  return drop
}
