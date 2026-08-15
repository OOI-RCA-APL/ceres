import { v7 } from 'uuid'

import {
  pagesOf,
  type Widget,
  type WidgetPage,
  type WidgetRow,
  widgetWidthSubdivisions,
  withPages,
} from '@/workspace/models'
import { createWidget, getWidgetInfo } from '@/workspace/registry'

// The narrowest a width may be squeezed to. A zero or negative width stores a widget nothing can
// grab and draws its neighbours past the row's edge.
const minWidthUnits = 1

/** Spread a row's widths back over `widgetWidthSubdivisions`, without touching any widget.

`keepIndices` names widths to leave alone, absorbing the difference into every other width or,
with `adjustMode` set to `after`, only into the ones that follow. No width goes below
`minWidthUnits`, and the result totals `widgetWidthSubdivisions` while any width can still give.
*/
export function resolveWidths(
  widths: number[],
  keepIndices?: number | number[],
  adjustMode: 'after' | 'other' = 'other',
): number[] {
  if (widths.length === 0) {
    return []
  }

  const kept = (
    keepIndices == null ? [] : Array.isArray(keepIndices) ? keepIndices : [keepIndices]
  ).filter((index) => index >= 0)

  const totalWidthUnits = widths.reduce((sum, current) => sum + current, 0)
  if (
    totalWidthUnits === widgetWidthSubdivisions &&
    widths.every((width) => width >= minWidthUnits)
  ) {
    return [...widths]
  }

  const indices = widths.map((_, index) => index)

  let adjusted: number[]
  if (kept.length === 0) {
    adjusted = indices
  } else {
    if (adjustMode === 'after') {
      adjusted = indices.slice(Math.max(...kept) + 1)
    } else {
      adjusted = indices.filter((index) => !kept.includes(index))
    }
  }

  if (adjusted.length === 0) {
    adjusted = indices
  }

  const resolved = [...widths]

  // A width already below the floor gives nothing so it is lifted first and the lift joins the
  // excess the others have to absorb.
  for (const index of indices) {
    const width = resolved[index] ?? 0
    if (width < minWidthUnits) {
      resolved[index] = minWidthUnits
    }
  }

  // Spread the excess over the adjustable widths, evenly, in passes. A width that would be taken
  // below the floor stops there, and what it could not give is spread over the rest on the next
  // pass so one pass per width bounds the loop.
  for (let pass = 0; pass <= widths.length; pass++) {
    const excess = resolved.reduce((sum, current) => sum + current, 0) - widgetWidthSubdivisions
    if (excess === 0) {
      break
    }

    const givers =
      excess > 0 ? adjusted.filter((index) => (resolved[index] ?? 0) > minWidthUnits) : adjusted
    if (givers.length === 0) {
      break
    }

    const share = excess / givers.length
    for (const index of givers) {
      const width = resolved[index] ?? 0
      resolved[index] = excess > 0 ? Math.max(width - share, minWidthUnits) : width - share
    }
  }

  // Round to whole units without moving the total, pushing the drift one unit at a time onto the
  // adjustable widths, into the widest when taking so nothing crosses the floor.
  const rounded = resolved.map((width) => Math.round(width))
  let drift =
    Math.round(resolved.reduce((sum, current) => sum + current, 0)) -
    rounded.reduce((sum, current) => sum + current, 0)
  while (drift !== 0) {
    const step = Math.sign(drift)
    const candidates =
      step > 0 ? adjusted : adjusted.filter((index) => (rounded[index] ?? 0) > minWidthUnits)
    if (candidates.length === 0) {
      break
    }

    const target = candidates.reduce((best, index) =>
      step < 0
        ? (rounded[index] ?? 0) > (rounded[best] ?? 0)
          ? index
          : best
        : (rounded[index] ?? 0) < (rounded[best] ?? 0)
          ? index
          : best,
    )
    rounded[target] = (rounded[target] ?? 0) + step
    drift -= step
  }

  return rounded
}

export function resolveWidgetWidths(
  widgets: Widget[],
  keepIndices?: number | number[],
  adjustMode: 'after' | 'other' = 'other',
) {
  const resolved = resolveWidths(
    widgets.map((widget) => widget.width),
    keepIndices,
    adjustMode,
  )

  for (const [index, widget] of widgets.entries()) {
    if (widget.width !== resolved[index]) {
      widget.width = resolved[index] as number
    }
  }
}

/** How grouping deals the taken widgets across the pages of the new widget. */
export type GroupSplit = 'widget' | 'row' | 'none'

/** Scale `widths` to fill a row, keeping their proportions.

A width at or below zero poisons the proportions so a row holding one is dealt out evenly
instead.
*/
export function filledWidths(widths: number[]): number[] {
  if (widths.length === 0) {
    return []
  }

  const usable = widths.every((width) => width > 0)
  const basis = usable ? widths : widths.map(() => 1)
  const basisTotal = usable ? widths.reduce((sum, current) => sum + current, 0) : widths.length
  const scaled = basis.map((width) => Math.round((width * widgetWidthSubdivisions) / basisTotal))

  // Rounding drift lands on the last width so the row still adds up exactly.
  const drift = widgetWidthSubdivisions - scaled.reduce((sum, current) => sum + current, 0)
  scaled[scaled.length - 1] = (scaled[scaled.length - 1] ?? 0) + drift

  return scaled
}

/** Group the widgets named by `ids` under a fresh widget of `type`, standing where the first
stood.

The taken widgets land on the holder's pages as `split` says, a page per widget, a page per
source row, or all on one page. Page rows keep their heights, the holder takes the taken widgets'
room in its own row, and emptied rows close up. With `frameless` set the taken widgets land
without their frames. Returns null when none of the named widgets stand in `rows`.
*/
export function planWidgetsGroup(
  rows: WidgetRow[],
  ids: string[],
  type: 'tabs' | 'carousel',
  split: GroupSplit,
  frameless: boolean = false,
): { rows: WidgetRow[]; holder: Widget } | null {
  const taking = new Set(ids)

  type Group = { row: WidgetRow; taken: Widget[]; staying: Widget[] }
  const groups = new Map<WidgetRow, Group>()
  for (const row of rows) {
    const taken = row.widgets.filter((widget) => taking.has(widget.id))
    if (taken.length > 0) {
      groups.set(row, {
        row,
        taken,
        staying: row.widgets.filter((widget) => !taking.has(widget.id)),
      })
    }
  }

  if (groups.size === 0) {
    return null
  }

  const groupList = [...groups.values()]

  function pageRow(source: WidgetRow, taken: Widget[]): WidgetRow {
    const widths = filledWidths(taken.map((widget) => widget.width))
    return {
      id: v7(),
      height: source.height,
      collapsed: source.collapsed,
      widgets: taken.map((widget, index) => ({
        ...widget,
        width: widths[index] ?? widget.width,
        frameless: frameless || widget.frameless,
      })),
    }
  }

  let pages: WidgetPage[]
  if (split === 'widget') {
    // Each page is named after its widget since the strip then stands for the widgets on it.
    pages = groupList.flatMap(({ row, taken }) =>
      taken.map((widget) => ({ id: v7(), name: widget.name, layout: [pageRow(row, [widget])] })),
    )
  } else if (split === 'row') {
    pages = groupList.map(({ row, taken }) => ({
      id: v7(),
      name: '',
      layout: [pageRow(row, taken)],
    }))
  } else {
    pages = [{ id: v7(), name: '', layout: groupList.map(({ row, taken }) => pageRow(row, taken)) }]
  }

  const base = createWidget(type)
  const first = groupList[0] as Group
  const width = Math.min(
    first.taken.reduce((sum, widget) => sum + widget.width, 0),
    widgetWidthSubdivisions,
  )
  const holder: Widget = { ...withPages(base, pages), width }

  const result: WidgetRow[] = []
  for (const row of rows) {
    const group = groups.get(row)
    if (group == null) {
      result.push(row)
    } else if (group === first) {
      // Everything before the first taken widget is staying so its index in the old row is also
      // the holder's place among what stays.
      const at = row.widgets.findIndex((widget) => taking.has(widget.id))
      const widgets = [...group.staying]
      widgets.splice(at, 0, holder)
      result.push({ ...row, widgets })
    } else if (group.staying.length > 0) {
      const widths = resolveWidths(group.staying.map((widget) => widget.width))
      result.push({
        ...row,
        widgets: group.staying.map((widget, index) => ({
          ...widget,
          width: widths[index] ?? widget.width,
        })),
      })
    }
  }

  return { rows: result, holder }
}

/** Dissolve the pages widget named `id` back into `rows`, its pages' rows standing in its place.

A row the widget shared stays ahead of them, holding the widgets that remain on it. Returns null
when no widget named `id` stands in `rows`, or when the named one holds no pages.
*/
export function planWidgetUngroup(
  rows: WidgetRow[],
  id: string,
): { rows: WidgetRow[]; released: Widget[] } | null {
  const at = rows.findIndex((row) => row.widgets.some((widget) => widget.id === id))
  if (at < 0) {
    return null
  }

  const row = rows[at] as WidgetRow
  const target = row.widgets.find((widget) => widget.id === id) as Widget
  const pages = pagesOf(target)
  if (pages.length === 0) {
    return null
  }

  const landing = pages.flatMap((page) => page.layout)
  const staying = row.widgets.filter((widget) => widget.id !== id)

  const result = [...rows]
  if (staying.length === 0) {
    result.splice(at, 1, ...landing)
  } else {
    const widths = resolveWidths(staying.map((widget) => widget.width))
    result.splice(
      at,
      1,
      {
        ...row,
        widgets: staying.map((widget, index) => ({
          ...widget,
          width: widths[index] ?? widget.width,
        })),
      },
      ...landing,
    )
  }

  return { rows: result, released: landing.flatMap((current) => current.widgets) }
}

/** The ID of the workspace's own layout, as opposed to one belonging to a widget's page. */
export const rootLayoutId = 'root'

/** A layout a workspace holds, by ID.

The workspace has one of its own, and every widget page anywhere inside it holds another, all
arranged the same way.
*/
export type WorkspaceLayoutRef = {
  id: string
  rows: WidgetRow[]

  /** Put a rearranged layout back where this one came from. */
  set: (rows: WidgetRow[]) => void
}

/** Collect every layout reachable from `root`, the workspace's own first. */
export function collectLayouts(
  root: WidgetRow[],
  setRoot: (rows: WidgetRow[]) => void,
): WorkspaceLayoutRef[] {
  const found: WorkspaceLayoutRef[] = [{ id: rootLayoutId, rows: root, set: setRoot }]

  function visit(rows: WidgetRow[]) {
    for (const row of rows) {
      for (const widget of row.widgets) {
        for (const page of pagesOf(widget)) {
          found.push({
            id: page.id,
            rows: page.layout,
            set: (replacement) => (page.layout = replacement),
          })
          visit(page.layout)
        }
      }
    }
  }

  visit(root)

  return found
}

/** A copy of `widget` under fresh IDs, all the way down.

A copy keeping any stored ID would leave two things answering to it wherever lookups go by ID.
*/
export function withFreshIds(widget: Widget): Widget {
  const copy: Widget = { ...widget, id: v7() }

  // Buttons carry IDs of their own.
  if (copy.type === 'controls') {
    copy.buttons = copy.buttons.map((button) => ({ ...button, id: v7() }))
  }

  // Chart series carry IDs of their own.
  if (copy.type === 'chart') {
    copy.particles = copy.particles.map((particle) => ({
      ...particle,
      series: particle.series.map((series) => ({ ...series, id: v7() })),
    }))
  }

  return withPages(copy, pagesOf(copy).map(withFreshPage))
}

/** A copy of `page` under fresh IDs, all the way down. */
export function withFreshPage(page: WidgetPage): WidgetPage {
  return {
    ...page,
    id: v7(),
    layout: page.layout.map((row) => ({
      ...row,
      id: v7(),
      widgets: row.widgets.map(withFreshIds),
    })),
  }
}

/** Every layout held inside `widgets`, however deep, which no drop may land inside. */
export function layoutsWithin(widgets: Widget[]): Set<string> {
  const found = new Set<string>()

  function visit(list: Widget[]) {
    for (const widget of list) {
      for (const page of pagesOf(widget)) {
        found.add(page.id)
        visit(page.layout.flatMap((row) => row.widgets))
      }
    }
  }

  visit(widgets)

  return found
}

/** Where a widget in hand would land.

Both indices read against the layout with that widget already taken out of it, which is the layout
its owner is looking at while the drag is in progress.
*/
export type WidgetPlacement = {
  /** Which layout it lands in, the workspace's own or a carousel slide's. */
  layout: string

  /** Row to drop into, or the index the new row takes when `column` is null. */
  row: number

  /** Insertion index within that row, or null to open a row of its own. */
  column: number | null
}

/** A row of a planned layout, in widget IDs, so it can be drawn before it is applied. */
export type PlannedRow = {
  id: string
  height: number
  collapsed: boolean
  widgets: string[]
}

/** The layouts a move settles on so they can be drawn before the move is applied.

A move touches the layout the widgets left and the one they arrive in, which are the same layout
whenever a drag stays where it started. Layouts the move leaves alone are absent.
*/
export type WidgetMovePlan = {
  layouts: Record<string, PlannedRow[]>

  /** The widths the move settles on, by widget ID. Widgets left at their own width are absent. */
  widths: Record<string, number>
}

/** Every widget in `layouts`, by ID. */
export function widgetsIn(layouts: Map<string, WidgetRow[]>): Map<string, Widget> {
  return new Map(
    [...layouts.values()]
      .flatMap((rows) => rows.flatMap((row) => row.widgets))
      .map((widget) => [widget.id, widget]),
  )
}

/** Whether a plan describes the layouts that are already there, down to the widths. */
export function planIsCurrent(plan: WidgetMovePlan, layouts: Map<string, WidgetRow[]>): boolean {
  for (const [layoutId, rows] of Object.entries(plan.layouts)) {
    const current = layouts.get(layoutId) ?? null
    if (current == null || rows.length !== current.length) {
      return false
    }

    for (const [index, row] of rows.entries()) {
      const currentRow = current[index] as WidgetRow
      if (
        row.id !== currentRow.id ||
        row.height !== currentRow.height ||
        row.collapsed !== currentRow.collapsed ||
        row.widgets.length !== currentRow.widgets.length
      ) {
        return false
      }

      for (const [position, widgetId] of row.widgets.entries()) {
        if (widgetId !== currentRow.widgets[position]?.id) {
          return false
        }
      }
    }
  }

  const widgets = widgetsIn(layouts)

  return Object.entries(plan.widths).every(
    ([widgetId, width]) => widgets.get(widgetId)?.width === width,
  )
}

/** Work out the layouts that moving `ids` to `placement` produces, changing nothing.

Widgets keep the rows they came from when the drop opens rows of its own, and a drop into an
existing row puts the whole selection there side by side. A null `placement` plans the removal
alone, for display while widgets are in hand. Returns null when no layout holds any of `ids`,
when the placement names a missing row, or when it names a layout a widget in hand carries.
*/
export function planWidgetsMove(
  layouts: Map<string, WidgetRow[]>,
  ids: string[],
  placement: WidgetPlacement | null,

  /** How tall each row actually renders, by row ID, where that differs from its stored height.
  A widget carried out of a stretched or squeezed slide row arrives at the size it was shown at. */
  shown?: Map<string, number>,
): WidgetMovePlan | null {
  const held = new Set(ids)

  /** The height a row actually renders at, which a widget leaving it carries away. */
  function heightOf(row: WidgetRow): number {
    return Math.round(shown?.get(row.id) ?? row.height)
  }

  // The layout the widgets came out of. A drag holds widgets from one layout at a time.
  let sourceId: string | null = null
  let source: WidgetRow[] | null = null
  for (const [layoutId, rows] of layouts) {
    if (rows.some((row) => row.widgets.some((widget) => held.has(widget.id)))) {
      sourceId = layoutId
      source = rows
      break
    }
  }
  if (sourceId == null || source == null) {
    return null
  }

  const widths: Record<string, number> = {}

  // What is in hand, grouped by source row in layout order. A group becomes a row again when the
  // drop opens rows rather than joining one.
  const groups: { row: WidgetRow; widgets: Widget[]; consumed: boolean }[] = []

  // Take the widgets out first so the placement's indices read against the layout without them.
  const rows = source.map((row) => {
    const taken = row.widgets.filter((widget) => held.has(widget.id))
    const remaining = row.widgets.filter((widget) => !held.has(widget.id))

    if (taken.length > 0) {
      groups.push({ row, widgets: taken, consumed: remaining.length === 0 })

      const resolved = resolveWidths(remaining.map((widget) => widget.width))
      for (const [index, widget] of remaining.entries()) {
        widths[widget.id] = resolved[index] as number
      }
    }

    return {
      id: row.id,
      height: row.height,
      collapsed: row.collapsed,
      widgets: remaining.map((widget) => widget.id),
    }
  })

  if (groups.length === 0) {
    return null
  }

  const kept = rows.filter((row) => row.widgets.length > 0)
  if (placement == null) {
    return { layouts: { [sourceId]: kept }, widths }
  }

  const carried = groups.flatMap((group) => group.widgets)

  // A carousel cannot be dropped onto a slide of its own, the layout would then hold the widget
  // holding it.
  if (layoutsWithin(carried).has(placement.layout)) {
    return null
  }

  // Arriving back in the source layout drops into the rows the widgets were just taken out of.
  const intoSource = placement.layout === sourceId
  const target = intoSource
    ? kept
    : (layouts.get(placement.layout)?.map((row) => ({
        id: row.id,
        height: row.height,
        collapsed: row.collapsed,
        widgets: row.widgets.map((widget) => widget.id),
      })) ?? null)
  if (target == null) {
    return null
  }

  const planned = () =>
    intoSource ? { [sourceId]: kept } : { [sourceId]: kept, [placement.layout]: target }

  if (placement.column == null) {
    const opened = groups.map((group) => {
      const resolved = resolveWidths(group.widgets.map((widget) => widget.width))
      for (const [index, widget] of group.widgets.entries()) {
        widths[widget.id] = resolved[index] as number
      }

      return {
        // An emptied row's ID passes to the row taking its place so a selection dropped back
        // where it started reads as no change.
        id: group.consumed ? group.row.id : v7(),
        height: heightOf(group.row),
        collapsed: group.row.collapsed,
        widgets: group.widgets.map((widget) => widget.id),
      }
    })

    target.splice(placement.row, 0, ...opened)
    return { layouts: planned(), widths }
  }

  const destinationRow = target[placement.row] ?? null
  if (destinationRow == null) {
    return null
  }

  destinationRow.widgets.splice(placement.column, 0, ...carried.map((widget) => widget.id))
  destinationRow.height = Math.max(
    destinationRow.height,
    ...groups.map((group) => heightOf(group.row)),
  )

  // Each arriving widget claims at most an even share of the row it joins, and the widgets
  // already there give up the difference. Widths are read across every layout since an arriving
  // widget's width comes from the one it left.
  const currentWidths = widgetsIn(layouts)
  const share = widgetWidthSubdivisions / destinationRow.widgets.length
  const resolved = resolveWidths(
    destinationRow.widgets.map((widgetId) => {
      const width = currentWidths.get(widgetId)?.width ?? 0

      return held.has(widgetId) ? Math.min(share, width) : width
    }),
    carried.map((_, offset) => (placement.column ?? 0) + offset),
  )
  for (const [index, widgetId] of destinationRow.widgets.entries()) {
    widths[widgetId] = resolved[index] as number
  }

  return { layouts: planned(), widths }
}

/** Work out the layouts that inserting `widgets` at `placement` produces, changing nothing.

The widgets stand for what a drop from outside the workspace would create, so only the
destination layout changes and a null `placement` plans nothing at all.
*/
export function planWidgetsInsert(
  layouts: Map<string, WidgetRow[]>,
  widgets: Widget[],
  placement: WidgetPlacement | null,
): WidgetMovePlan | null {
  if (placement == null || widgets.length === 0) {
    return null
  }

  const target =
    layouts.get(placement.layout)?.map((row) => ({
      id: row.id,
      height: row.height,
      collapsed: row.collapsed,
      widgets: row.widgets.map((widget) => widget.id),
    })) ?? null
  if (target == null) {
    return null
  }

  const widths: Record<string, number> = {}

  if (placement.column == null) {
    const resolved = resolveWidths(widgets.map((widget) => widget.width))
    for (const [index, widget] of widgets.entries()) {
      widths[widget.id] = resolved[index] as number
    }

    target.splice(placement.row, 0, {
      id: v7(),
      height: Math.max(
        ...widgets.map((widget) => getWidgetInfo(widget.type).options.initialHeight),
      ),
      collapsed: false,
      widgets: widgets.map((widget) => widget.id),
    })

    return { layouts: { [placement.layout]: target }, widths }
  }

  const destinationRow = target[placement.row] ?? null
  if (destinationRow == null) {
    return null
  }

  destinationRow.widgets.splice(placement.column, 0, ...widgets.map((widget) => widget.id))
  destinationRow.height = Math.max(
    destinationRow.height,
    ...widgets.map((widget) => getWidgetInfo(widget.type).options.minHeight),
  )

  // Each arriving widget claims at most an even share of the row it joins, and the widgets
  // already there give up the difference. Arriving widths are read from the widgets in hand
  // since no layout holds them yet.
  const currentWidths = widgetsIn(layouts)
  const arriving = new Map(widgets.map((widget) => [widget.id, widget]))
  const share = widgetWidthSubdivisions / destinationRow.widgets.length
  const resolved = resolveWidths(
    destinationRow.widgets.map((widgetId) => {
      const held = arriving.get(widgetId)
      if (held != null) {
        return Math.min(share, held.width)
      }

      return currentWidths.get(widgetId)?.width ?? 0
    }),
    widgets.map((_, offset) => (placement.column ?? 0) + offset),
  )
  for (const [index, widgetId] of destinationRow.widgets.entries()) {
    widths[widgetId] = resolved[index] as number
  }

  return { layouts: { [placement.layout]: target }, widths }
}
