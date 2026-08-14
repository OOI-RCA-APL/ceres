import { useEventListener } from '@vueuse/core'
import { debounce } from 'lodash-es'
import { defineStore } from 'pinia'
import { v7 } from 'uuid'
import {
  computed,
  inject,
  type MaybeRef,
  onScopeDispose,
  provide,
  reactive,
  readonly,
  unref,
  watch,
  watchEffect,
} from 'vue'
import * as z from 'zod'

import { useAccess } from '@/api/access'
import type { Address } from '@/api/address'
import { AddressSelector, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient, useQuery } from '@/api/client'
import { Failure } from '@/errors'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { workspaceInjectionKey } from '@/symbols'
import { workspaceQueryKey } from '@/tabs'
import { copyText, deepClone, downloadFile, isStructurallyEqual, selectFile } from '@/utilities'
import {
  collectLayouts,
  filledWidths,
  planIsCurrent,
  planWidgetsGroup,
  planWidgetsMove,
  planWidgetUngroup,
  resolveWidgetWidths,
  rootLayoutId,
  widgetsIn,
  withFreshIds,
  type GroupSplit,
  type WidgetPlacement,
  type WorkspaceLayoutRef,
} from '@/workspace/layout'
import {
  comparableWorkspaceData,
  widgetWidthSubdivisions,
  withoutMeta,
  type Widget,
  type WidgetClipboard,
  WidgetClipboardModel,
  type WidgetRow,
  WidgetRowModel,
  type WidgetType,
  type Workspace,
  type WorkspaceData,
  type WorkspaceEdit,
  WorkspaceEditModel,
  type WorkspaceInput,
  WorkspaceModel,
} from '@/workspace/models'
import { createWidget, getWidgetInfo, openedRowFor } from '@/workspace/registry'

export type WorkspaceContext = ReturnType<typeof createWorkspaceContext>

/** Handlers a workspace page instance exposes to its hosting page, which renders the tab
strip the workspace is shown on. */
export type WorkspaceHeaderActions = {
  rename: (name: string) => void
  openSettings: () => void
  undo: () => void
  redo: () => void
  duplicate: () => void
  exportFile: () => void
  promptDelete: () => void
  promptCommit: () => void
  promptRevert: () => void
  startViewingOriginal: () => void
  stopViewingOriginal: () => void
}

/** State a workspace page instance exposes alongside `WorkspaceHeaderActions`, read-only. */
export type WorkspaceHeaderState = {
  edited: boolean
  canManage: boolean
  canEdit: boolean
  canUndo: boolean
  canRedo: boolean
  isViewingOriginal: boolean
}

export type Drag = {
  /** The widget the press landed on. */
  widget: Widget

  /** Everything in hand, in layout order, `widget` among it. */
  widgets: Widget[]

  /** The layout everything came from. A selection is always made within one layout. */
  layout: string

  /** Takes the release of a drag carrying widgets from outside any layout, called with where
  they landed or null when the drag never took hold anywhere. The widgets in hand stand for
  what would be created, so releasing moves nothing itself. */
  drop?: (placement: WidgetPlacement | null) => void
}

/** How a widget joins what is already picked out when it is chosen. */
export type SelectMode = 'replace' | 'toggle' | 'extend'

function createWorkspaceContext(workspaceId: MaybeRef<string>) {
  const auth = useAuth()
  const access = useAccess()
  const workspaces = useWorkspaces()
  const id = $computed(() => unref(workspaceId))

  const query = useQuery({
    queryKey: computed(() => ['workspace-context', id, auth.user?.id]),
    experimental_prefetchInRender: true,
    queryFn: async () => {
      return { workspace: await workspaces.get(id) }
    },
  })

  const workspace = $computed(
    () =>
      (query.data.value?.workspace
        ? readonly(query.data.value.workspace)
        : null) as Workspace | null,
  )

  const scope = $computed(() => workspace?.scope ?? null)

  /** Whether the caller may edit and manage this workspace, which are the same right. */
  function isWritable(): boolean {
    if (workspace == null) {
      return false
    }
    if (workspace.owner_id != null) {
      return workspace.owner_id === auth.user?.id
    }

    return access.canManage(workspace.scope.toString())
  }

  function resolveAddress(
    value: string | AddressSelector | null | undefined,
  ): AddressSelector | null {
    if (value == null) {
      return null
    }

    return AddressSelector.parse(value).asAbsolute(scope)
  }

  // Whether this workspace is bound to a component rather than the engine root. The root
  // contains every component so a workspace placed there restricts nothing.
  const isBound = $computed(() => scope != null && !scope.isEngine)

  /** Whether an address falls within this workspace's placement.
   *
   * A workspace at the engine root admits every component, one bound to a component admits that
   * component and its descendants. Must agree with what `resolveFilterAddress` produces.
   */
  function isWithinScope(address: Address | string): boolean {
    if (scope == null || scope.isEngine) {
      return true
    }

    const base = scope.toString()
    const value = address.toString()
    return value === base || value.startsWith(`${base}.`)
  }

  // Like `resolveAddress`, but an unset value falls back to the scope's own subtree. A record
  // widget with no address chosen must default to the scope, not to every component.
  function resolveFilterAddress(
    value: string | AddressSelector | null | undefined,
  ): AddressSelector | null {
    if (value == null) {
      return scope == null ? null : AddressSelector.parse(`${scope}:all`)
    }

    return AddressSelector.parse(value).asAbsolute(scope)
  }

  let data = $ref<WorkspaceData | null>(null)

  // Undo history for the working copy, capped so a long editing session cannot grow without
  // bound. Snapshots are recorded on the same debounce as the autosave, which groups a burst of
  // drags or keystrokes into one undo step rather than one per frame.
  const historyLimit = 50
  let history = $ref<WorkspaceData[]>([])
  let historyIndex = $ref(-1)

  const canUndo = $computed(() => historyIndex > 0)
  const canRedo = $computed(() => historyIndex >= 0 && historyIndex < history.length - 1)

  function recordHistory() {
    if (data == null) {
      return
    }

    // An undo or redo assigns a state already in the history, which must not be recorded again
    // or it would erase the redo tail it just moved through.
    if (historyIndex >= 0 && isStructurallyEqual(data, history[historyIndex])) {
      return
    }

    const snapshot = deepClone(data) as WorkspaceData
    const kept = [
      ...history.slice(Math.max(0, history.length - historyLimit + 1), historyIndex + 1),
      snapshot,
    ]
    history = kept
    historyIndex = kept.length - 1
  }

  function undo() {
    if (!canUndo) {
      return
    }

    historyIndex--
    data = deepClone(history[historyIndex]) as WorkspaceData
  }

  function redo() {
    if (!canRedo) {
      return
    }

    historyIndex++
    data = deepClone(history[historyIndex]) as WorkspaceData
  }

  async function saveEdit() {
    if (workspace == null || data == null) {
      return
    }

    console.log(`Saving edit for workspace ${id}.`)
    await workspaces.assignEdit(id, data)
  }

  watch(
    () => data,
    debounce(() => {
      recordHistory()
      void saveEdit()
    }, 500),
    { deep: true },
  )

  useEventListener(window, 'beforeunload', async () => {
    try {
      await saveEdit()
    } catch {
      // Ignore.
    }
  })

  // The save watcher is debounced, so an edit made just before the hosting page unmounts, such
  // as the workspace content being hidden, would otherwise never reach the server.
  onScopeDispose(() => {
    void saveEdit()
  })

  const edited = $computed(() => {
    if (data == null || workspace == null) {
      return false
    }

    return !isStructurallyEqual(
      comparableWorkspaceData(data),
      comparableWorkspaceData(workspace.data),
    )
  })

  async function rename(newName: string) {
    return await workspaces.rename(id, newName)
  }

  async function save() {
    if (workspace == null || data == null) {
      return
    }

    console.log(`Saving workspace changes to ${id}.`)
    const result = await update({ data })
    await refresh()
    return result
  }

  async function revert() {
    if (workspace == null || data == null) {
      return
    }

    await refresh()
    if (workspace == null || data == null) {
      return
    }

    console.log(`Discarding workspace changes to ${id}.`)
    data = deepClone(workspace.data) as WorkspaceData
    await workspaces.assignEdit(id, data)
    return workspace
  }

  async function update(data: Partial<Workspace>) {
    return await workspaces.update(id, data)
  }

  async function del() {
    return await workspaces.delete(id)
  }

  async function exportFile() {
    if (workspace == null || data == null) {
      return
    }

    await workspaces.exportFile({
      name: workspace.name,
      data,
    })
  }

  /** Every layout this workspace holds, its own and each carousel slide's, in that order. */
  function layoutRefs(): WorkspaceLayoutRef[] {
    if (data == null) {
      return []
    }

    const current = data
    return collectLayouts(current.layout, (rows) => (current.layout = rows))
  }

  function layoutMap(): Map<string, WidgetRow[]> {
    return new Map(layoutRefs().map((layout) => [layout.id, layout.rows]))
  }

  function findLayout(id: string): WorkspaceLayoutRef | null {
    return layoutRefs().find((layout) => layout.id === id) ?? null
  }

  /** A row opened to hold `widget`, no taller than the widget requires.

  Opening at the default row height would leave a short widget above a band of empty space.
  */
  function openedRow(widgets: Widget[], opening: Widget): WidgetRow {
    return WidgetRowModel.parse({
      widgets,
      height: getWidgetInfo(opening.type).options.initialHeight,
    })
  }

  function insertWidget(
    widget: Widget,
    row: number,
    column: number = 0,
    layoutId: string = rootLayoutId,
  ) {
    const layout = findLayout(layoutId)
    if (layout == null) {
      return
    }

    const rows = layout.rows
    row = Math.min(rows.length, row)
    const widgets = [...(rows[row]?.widgets ?? [])]
    widgets.splice(column, 0, widget)
    widget.width = Math.min(widgetWidthSubdivisions / widgets.length, widget.width)
    resolveWidgetWidths(widgets, widgets.indexOf(widget))

    const rowObject = rows[row] ?? null
    if (row < 0) {
      layout.set([openedRow(widgets, widget), ...rows])
    } else if (rowObject == null) {
      layout.set([...rows, openedRow(widgets, widget)])
    } else {
      const minHeight = getWidgetInfo(widget.type).options.minHeight
      if (rowObject.height < minHeight) {
        rowObject.height = minHeight
      }

      rowObject.widgets = widgets
    }
  }

  /** Insert widgets arriving from outside the workspace at a drop placement.

  A null column opens a row of their own at that index, and a column splices them into the
  row side by side.
  */
  function insertWidgetsAt(widgets: Widget[], placement: WidgetPlacement) {
    if (widgets.length === 0) {
      return
    }

    if (placement.column != null) {
      for (const [offset, widget] of widgets.entries()) {
        insertWidget(widget, placement.row, placement.column + offset, placement.layout)
      }

      return
    }

    const layout = findLayout(placement.layout)
    if (layout == null) {
      return
    }

    resolveWidgetWidths(widgets)
    const rows = layout.rows
    const index = Math.max(0, Math.min(rows.length, placement.row))
    layout.set([...rows.slice(0, index), openedRowFor(widgets), ...rows.slice(index)])
  }

  function addWidget(
    type: WidgetType,
    row: number,
    column: number = 0,
    layoutId: string = rootLayoutId,
  ) {
    if (data == null) {
      return null
    }

    const widget = createWidget(type)
    insertWidget(widget, row, column, layoutId)

    return widget
  }

  function deleteWidgets(ids: string[]) {
    if (data == null || ids.length === 0) {
      return
    }

    const removed = new Set(ids)

    // Every layout is searched since widgets are deleted by ID and carousel slides hold
    // widgets too.
    for (const layout of layoutRefs()) {
      const rows: WidgetRow[] = []
      let changed = false

      for (const row of layout.rows) {
        const remaining = row.widgets.filter((widget) => !removed.has(widget.id))
        if (remaining.length === row.widgets.length) {
          rows.push(row)
          continue
        }

        changed = true
        if (remaining.length === 0) {
          continue
        }

        resolveWidgetWidths(remaining)
        rows.push({ ...row, widgets: remaining })
      }

      if (changed) {
        layout.set(rows)
      }
    }
  }

  function deleteWidget(id: string) {
    deleteWidgets([id])
  }

  function getWidget(id: string) {
    for (const layout of layoutRefs()) {
      const found = layout.rows.flatMap((row) => row.widgets).find((widget) => widget.id === id)
      if (found != null) {
        return found
      }
    }

    return null
  }

  /** Put `replacement` where the widget named `id` stands, keeping its ID and width. */
  function replaceWidget(id: string, replacement: Widget) {
    for (const layout of layoutRefs()) {
      const existing = layout.rows.flatMap((row) => row.widgets).find((widget) => widget.id === id)
      if (existing == null) {
        continue
      }

      const kept: Widget = { ...replacement, id: existing.id, width: existing.width }
      layout.set(
        layout.rows.map((row) =>
          row.widgets.some((widget) => widget.id === id)
            ? { ...row, widgets: row.widgets.map((widget) => (widget.id === id ? kept : widget)) }
            : row,
        ),
      )

      return kept
    }

    return null
  }

  /** Group the widgets named by `ids` under a fresh widget of `type`, standing in their place. */
  function groupWidgets(
    ids: string[],
    type: 'tabs' | 'carousel',
    split: GroupSplit = 'widget',
    frameless: boolean = false,
  ) {
    if (data == null || ids.length === 0) {
      return null
    }

    // A selection never spans layouts so the first layout that produces a plan held the widgets.
    for (const layout of layoutRefs()) {
      const plan = planWidgetsGroup(layout.rows, ids, type, split, frameless)
      if (plan == null) {
        continue
      }

      layout.set(plan.rows)

      // The holder stands in for what it took so it becomes the selection.
      selectionLayout = layout.id
      selection = [plan.holder.id]
      selectionAnchor = plan.holder.id

      return plan.holder
    }

    return null
  }

  /** Dissolve the pages widget named `id`, its pages' rows standing in its place. */
  function ungroupWidget(id: string) {
    if (data == null) {
      return
    }

    for (const layout of layoutRefs()) {
      const plan = planWidgetUngroup(layout.rows, id)
      if (plan == null) {
        continue
      }

      layout.set(plan.rows)

      // The released widgets become the selection.
      selectionLayout = layout.id
      selection = plan.released.map((widget) => widget.id)
      selectionAnchor = plan.released[plan.released.length - 1]?.id ?? null

      return
    }
  }

  function moveWidgets(ids: string[], placement: WidgetPlacement) {
    if (data == null) {
      return
    }

    const refs = layoutRefs()
    const layouts = new Map(refs.map((layout) => [layout.id, layout.rows]))
    const plan = planWidgetsMove(layouts, ids, placement)
    if (plan == null) {
      return
    }

    // A drop that lands widgets back where they came from changes nothing so skip the rewrite
    // and the server edit.
    if (planIsCurrent(plan, layouts)) {
      return
    }

    const widgets = widgetsIn(layouts)

    for (const [widgetId, width] of Object.entries(plan.widths)) {
      const widget = widgets.get(widgetId)
      if (widget != null) {
        widget.width = width
      }
    }

    // The selection moves with the widgets so a widget dragged into a slide stays selected.
    if (selection.length > 0 && selection.every((id) => ids.includes(id))) {
      selectionLayout = placement.layout
    }

    for (const [layoutId, rows] of Object.entries(plan.layouts)) {
      const layout = refs.find((candidate) => candidate.id === layoutId) ?? null
      layout?.set(
        rows.map((row) => ({
          id: row.id,
          height: row.height,
          collapsed: row.collapsed,
          widgets: row.widgets
            .map((widgetId) => widgets.get(widgetId))
            .filter((widget) => widget != null),
        })),
      )
    }
  }

  // The selected widgets, held as IDs so a layout rebuilt underneath them keeps the selection.
  let selection = $ref<string[]>([])

  // The layout the selection was made in. A selection belongs to one layout at a time.
  let selectionLayout = $ref<string>(rootLayoutId)

  // The widget a range extends from, whichever one was last chosen on its own.
  let selectionAnchor = $ref<string | null>(null)

  function widgetOrder(layoutId: string = selectionLayout): string[] {
    const rows = layoutMap().get(layoutId) ?? []

    return rows.flatMap((row) => row.widgets.map((widget) => widget.id))
  }

  function isSelected(id: string) {
    return selection.includes(id)
  }

  function clearSelection() {
    selection = []
    selectionAnchor = null
  }

  /** Work in `layoutId` from now on, with nothing selected.

  Pressing an empty layout is how it becomes the paste target since it has no widget to select.
  */
  function focusLayout(layoutId: string) {
    selectionLayout = layoutId
    selection = []
    selectionAnchor = null
  }

  function selectWidget(id: string, mode: SelectMode = 'replace', layoutId: string = rootLayoutId) {
    // Selecting in another layout drops the previous selection so there is nothing to extend
    // from or toggle against.
    if (layoutId !== selectionLayout) {
      selectionLayout = layoutId
      selection = [id]
      selectionAnchor = id
      return
    }

    const order = widgetOrder(layoutId)

    if (mode === 'extend' && selectionAnchor != null) {
      const from = order.indexOf(selectionAnchor)
      const to = order.indexOf(id)
      if (from !== -1 && to !== -1) {
        selection = order.slice(Math.min(from, to), Math.max(from, to) + 1)
        return
      }
    }

    if (mode === 'toggle') {
      selection = isSelected(id)
        ? selection.filter((current) => current !== id)
        : [...selection, id]
      selectionAnchor = id
      return
    }

    selection = [id]
    selectionAnchor = id
  }

  /** The selection as text for the system clipboard, or null when nothing is selected. */
  function copySelection(): string | null {
    const layout = findLayout(selectionLayout)
    if (layout == null || selection.length === 0) {
      return null
    }

    const rows = layout.rows
      .map((row) => ({ ...row, widgets: row.widgets.filter((widget) => isSelected(widget.id)) }))
      .filter((row) => row.widgets.length > 0)

    return JSON.stringify({ ceres: 'widgets', rows } satisfies WidgetClipboard, null, 2)
  }

  /** Put the widgets `text` holds into the layout and select them.

  Returns how many landed, zero when the text is not a widget copy.
  */
  function pasteWidgets(text: string): number {
    // Pastes land in the layout being worked in, even when copied from another workspace.
    const layout = findLayout(selectionLayout) ?? findLayout(rootLayoutId)
    if (layout == null) {
      return 0
    }

    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return 0
    }

    const clipboard = WidgetClipboardModel.safeParse(parsed).data ?? null
    if (clipboard == null) {
      return 0
    }

    const pasted: WidgetRow[] = []
    for (const row of clipboard.rows) {
      // Fresh IDs so pasting twice creates two of everything.
      const widgets = row.widgets.map(withFreshIds)
      if (widgets.length === 0) {
        continue
      }

      resolveWidgetWidths(widgets)
      pasted.push({ id: v7(), height: row.height, collapsed: row.collapsed, widgets })
    }

    if (pasted.length === 0) {
      return 0
    }

    // Landing under the selection puts a paste beside its source rather than at the end of the
    // workspace.
    let after = layout.rows.length
    for (const [index, row] of layout.rows.entries()) {
      if (row.widgets.some((widget) => isSelected(widget.id))) {
        after = index + 1
      }
    }

    const rows = [...layout.rows]
    rows.splice(after, 0, ...pasted)
    layout.set(rows)

    selectionLayout = layout.id
    selection = pasted.flatMap((row) => row.widgets.map((widget) => widget.id))
    selectionAnchor = selection[selection.length - 1] ?? null

    return selection.length
  }

  // The selection follows what the layouts actually hold since deletion or undo can remove
  // selected widgets or the layout they were in.
  watchEffect(() => {
    const present = new Set(widgetOrder(selectionLayout))
    const kept = selection.filter((id) => present.has(id))
    if (kept.length !== selection.length) {
      selection = kept
      if (selectionAnchor != null && !present.has(selectionAnchor)) {
        selectionAnchor = null
      }
    }
  })

  function duplicateWidget(
    id: string,
    toRow: number,
    toColumn: number,
    layoutId: string = rootLayoutId,
  ) {
    const widget = getWidget(id)
    if (widget == null) {
      return null
    }

    const copy = withFreshIds(deepClone(widget))
    insertWidget(copy, toRow, toColumn, layoutId)
    return copy
  }

  /** Where a widget currently stands, or null when no layout holds it. */
  function positionOf(id: string): { layout: string; row: number; column: number } | null {
    for (const layout of layoutRefs()) {
      for (const [rowIndex, rowObject] of layout.rows.entries()) {
        const columnIndex = rowObject.widgets.findIndex((widget) => widget.id === id)
        if (columnIndex >= 0) {
          return { layout: layout.id, row: rowIndex, column: columnIndex }
        }
      }
    }

    return null
  }

  /** Duplicate every widget in `ids`, each copy landing directly after its original.

  Positions are looked up one duplicate at a time since each insertion shifts the columns
  after it.
  */
  function duplicateWidgets(ids: string[]) {
    for (const id of ids) {
      const position = positionOf(id)
      if (position != null) {
        duplicateWidget(id, position.row, position.column + 1, position.layout)
      }
    }
  }

  // Reload requests by widget ID, read into each widget's render key. Transient view state,
  // sized by the widgets of this one workspace and freed with the context.
  const reloadStamps = reactive(new Map<string, number>())

  function requestReload(ids: string[]) {
    for (const id of ids) {
      reloadStamps.set(id, (reloadStamps.get(id) ?? 0) + 1)
    }
  }

  function reloadStamp(id: string): number {
    return reloadStamps.get(id) ?? 0
  }

  watchEffect(() => {
    for (const layout of layoutRefs()) {
      if (layout.rows.some((row) => row.widgets.length === 0)) {
        layout.set(layout.rows.filter((row) => row.widgets.length > 0))
      }
    }
  })

  // A stored width can be broken, negative or with a total drifted off the row's span. Broken
  // rows are spread back over the full span so they never draw wider than the workspace.
  watchEffect(() => {
    for (const layout of layoutRefs()) {
      for (const row of layout.rows) {
        const widths = row.widgets.map((widget) => widget.width)
        const total = widths.reduce((sum, current) => sum + current, 0)
        if (
          widths.length > 0 &&
          (total !== widgetWidthSubdivisions || widths.some((width) => width <= 0))
        ) {
          const fixed = filledWidths(widths)
          for (const [index, widget] of row.widgets.entries()) {
            widget.width = fixed[index] ?? widget.width
          }
        }
      }
    }
  })

  async function afterFetch() {
    if (data == null) {
      // A failed fetch falls through to stored data, the same as there being no pending edit.
      let edit: WorkspaceEdit | null = null
      try {
        edit = await workspaces.getEdit(id)
      } catch {
        // Ignore.
      }

      data = edit?.data ?? deepClone(workspace?.data ?? null) ?? null

      // Seed the history with the loaded state so the first edit has something to undo back to.
      if (data != null) {
        history = [deepClone(data) as WorkspaceData]
        historyIndex = 0
      }
    }
  }

  // True while a workspace is being fetched and its working copy seeded so a host can tell an
  // empty context apart from one whose workspace does not exist.
  let loading = $ref(true)

  async function load() {
    await query.promise.value
    await afterFetch()
    loading = false
  }

  async function refresh() {
    await query.refetch()
    await workspaces.refresh()
    await afterFetch()
  }

  // The context follows its workspace ID so a host switching workspaces keeps its chrome
  // mounted. The working copy and history belong to the previous workspace so clear them first.
  watch(
    () => id,
    async () => {
      loading = true
      data = null
      history = []
      historyIndex = -1
      await query.promise.value
      await afterFetch()
      loading = false
    },
  )

  return reactive({
    load,
    refresh,
    loading: computed(() => loading),
    name: computed(() => workspace?.name ?? null),
    scope: computed(() => scope),
    resolveAddress,
    resolveFilterAddress,
    isWithinScope,
    isBound: computed(() => isBound),
    owner: computed(() => workspace?.owner_id ?? null),
    isPrivate: computed(() => workspace?.owner_id != null),
    isEnginePlaced: computed(() => workspace?.scope.isEngine === true),
    originalData: computed(() => workspace?.data ?? null),
    data: computed(() => data),
    edited: computed(() => edited),
    canUndo: computed(() => canUndo),
    canRedo: computed(() => canRedo),
    undo,
    redo,
    delete: del,
    rename,
    update,
    save,
    revert,
    exportFile,
    getWidget,
    layouts: computed(() => layoutRefs()),
    insertWidget,
    insertWidgetsAt,
    addWidget,
    deleteWidget,
    deleteWidgets,
    moveWidgets,
    duplicateWidgets,
    requestReload,
    reloadStamp,
    replaceWidget,
    groupWidgets,
    ungroupWidget,
    drag: null as Drag | null,
    selection: computed(() => selection),
    selectionLayout: computed(() => selectionLayout),
    selectedWidgets: computed(() => {
      const rows = layoutMap().get(selectionLayout) ?? []

      return rows.flatMap((row) => row.widgets).filter((widget) => isSelected(widget.id))
    }),
    isSelected,
    selectWidget,
    clearSelection,
    focusLayout,
    copySelection,
    pasteWidgets,
    // A workspace's access is its placement's, except a private workspace belongs to its owner
    // alone.
    canView: computed(() => {
      if (workspace == null) {
        return false
      }
      if (workspace.owner_id != null) {
        return workspace.owner_id === auth.user?.id
      }

      return access.canView(workspace.scope.toString())
    }),
    canEdit: computed(() => isWritable()),
    canManage: computed(() => isWritable()),
  })
}

export function provideWorkspace(id: MaybeRef<string>) {
  const context = createWorkspaceContext(id)
  provide(workspaceInjectionKey, context)
  return context
}

export function useWorkspace() {
  const workspace = inject(workspaceInjectionKey)
  if (workspace == null) {
    throw new Error('Workspace context not found.')
  }

  return workspace
}

export const useWorkspaces = defineStore('workspaces', () => {
  const navigation = useNavigation()
  const client = useClient()
  const auth = useAuth()
  const notify = useNotify()

  function getUserId() {
    if (auth.user == null) {
      throw new Error('Not logged in.')
    }

    return auth.user.id
  }

  async function get(id: string) {
    return await client.get(`/api/workspaces/${id}`, {
      parse: WorkspaceModel,
    })
  }

  // Every workspace the caller may see. The server limits to viewable placements plus the
  // private workspaces they own.
  async function getAll() {
    return await client.get(`/api/workspaces`, {
      parse: z.array(WorkspaceModel),
    })
  }

  async function listScoped(scope: Address) {
    return await client.get(`/api/workspaces`, {
      parse: z.array(WorkspaceModel),
      query: {
        scope: scope.toString(),
      },
    })
  }

  const query = useQuery({
    queryKey: computed(() => ['workspaces', auth.user?.id]),
    queryFn: async () => {
      return { all: await getAll() }
    },
    enabled: computed(() => auth.user != null),
  })

  async function load() {
    await query.promise.value
  }

  async function refresh() {
    await query.refetch()
  }

  const allWorkspaces = $computed(
    () => new Map((query.data.value?.all ?? []).map((workspace) => [workspace.id, workspace])),
  )

  async function create(
    workspace?: Omit<WorkspaceInput, 'name'> & { name?: string },
  ): Promise<Workspace> {
    const prepared = WorkspaceModel.parse({ name: 'Workspace', ...workspace })
    const result = await client.post(`/api/workspaces`, {
      data: prepared,
      parse: WorkspaceModel,
    })
    await refresh()
    return result
  }

  async function update(id: string, data: Partial<Workspace>) {
    const result = await client.patch(`/api/workspaces/${id}`, {
      data: WorkspaceModel.partial().parse(data),
      parse: WorkspaceModel,
    })
    await refresh()
    return result
  }

  async function rename(id: string, name: string) {
    return await update(id, { name })
  }

  /** Show a workspace on home by naming it in the query.

  Home reads the query and adds the workspace to its strip so a link, a sidebar click, and an
  action all arrive the same way. The workspace keeps its placement.
  */
  async function open(id: string) {
    await navigation.push({ path: '/', query: { [workspaceQueryKey]: id } })
  }

  /** Copy a link that opens workspaces on the page a placement belongs to.

  The query is read on arrival and removed from the bar so a shareable link exists only through
  this.
  */
  async function copyLink(placement: string, ids: string[]) {
    const path = placement === engineRoot ? '/' : `/components/${placement}`
    const { href } = navigation.resolve({ path, query: { [workspaceQueryKey]: ids } })

    await copyText(window.location.origin + href)
    notify.success(ids.length > 1 ? 'Links copied to clipboard.' : 'Link copied to clipboard.')
  }

  async function del(id: string) {
    const result = await client.delete(`/api/workspaces/${id}`, {
      parse: WorkspaceModel,
    })
    notify.success('Workspace deleted.')
    await refresh()
    return result
  }

  /** This user's pending edit for `workspaceId`, null when none exists.

  Rethrows on any failure other than not-found, so a caller reconciling the edit against fresh
  data can tell "no edit" apart from "could not check."
  */
  async function getEdit(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      return await client.get(`/api/users/${auth.user.id}/workspace-edits/${workspaceId}`, {
        parse: WorkspaceEditModel,
      })
    } catch (error) {
      if (error instanceof Failure && error.error.type === 'not-found-error') {
        return null
      }

      throw error
    }
  }

  async function assignEdit(workspaceId: string, data: WorkspaceData) {
    return await client.put(`/api/users/${getUserId()}/workspace-edits/${workspaceId}`, {
      data: {
        // `meta` is shared so an edit carries content only. Committing an edit must not restore
        // the tab order that was in force when the edit began.
        data: withoutMeta(data),
      },
      parse: WorkspaceEditModel,
    })
  }

  // Lets the component-scoped tab strip learn which workspaces still have unsaved edits
  // without loading each one's full context.
  async function getEdits(workspaceIds: string[]) {
    if (auth.user == null || workspaceIds.length === 0) {
      return []
    }

    return await client.get(`/api/users/${auth.user.id}/workspace-edits`, {
      parse: z.array(WorkspaceEditModel),
      query: {
        'workspace-id': workspaceIds,
      },
    })
  }

  async function discardEdit(workspaceId: string) {
    if (auth.user == null) {
      return null
    }

    try {
      await client.delete(`/api/users/${auth.user.id}/workspace-edits/${workspaceId}`, {
        parse: WorkspaceEditModel,
      })
    } catch {
      return null
    }
  }

  async function exportFile(workspaceOrId: string | WorkspaceInput) {
    const workspace = typeof workspaceOrId === 'string' ? await get(workspaceOrId) : workspaceOrId
    if (workspace == null) {
      notify.error('Workspace not found.')
      return
    }

    const json = JSON.stringify(
      {
        name: workspace.name,
        data: workspace.data,
      },
      null,
      2,
    )

    downloadFile(`${workspace.name}.workspace.json`, json)
  }

  /** Import exported workspace files, placing each one on `placement`. */
  async function importWorkspaces(
    files: Iterable<File>,
    placement?: { scope?: Address; owner_id?: string | null },
  ) {
    const imported: Workspace[] = []

    for (const file of files) {
      let parsed: unknown
      try {
        parsed = JSON.parse(await file.text())
      } catch {
        notify.error(`Import of '${file.name}' failed. Invalid JSON.`)
        continue
      }

      const { data: workspace, error } = WorkspaceModel.safeParse(parsed)
      if (error != null) {
        notify.error(`Import of '${file.name}' failed. Invalid workspace file. ${error.message}`)
        continue
      }

      // Only the name and contents travel so the import lands where the user dropped it.
      const created = await create({
        name: workspace.name,
        data: workspace.data,
        ...placement,
      })
      imported.push(created)
    }

    if (imported.length > 0) {
      notify.success(`${imported.length} workspace(s) imported successfully.`)
    }

    return imported
  }

  async function importFiles(placement?: { scope?: Address; owner_id?: string | null }) {
    const files = await selectFile({ multiple: true, accept: 'application/json' })
    if (files == null) {
      return null
    }

    return await importWorkspaces(files, placement)
  }

  return {
    load,
    refresh,
    all: computed(() => [...allWorkspaces.values()]),
    get,
    getAll,
    listScoped,
    create,
    rename,
    update,
    open,
    copyLink,
    delete: del,
    getEdit,
    getEdits,
    assignEdit,
    discardEdit,
    importFiles,
    importWorkspaces,
    exportFile,
  }
})
