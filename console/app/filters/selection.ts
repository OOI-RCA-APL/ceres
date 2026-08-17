import type { RecordKind } from '@/filters/definitions'
import {
  withFreshIds,
  withGrouped,
  withInserted,
  withMoved,
  withUngrouped,
  withoutItems,
} from '@/filters/model'
import type { FilterItem, FilterQuery } from '@/filters/model'
import type { SelectMode } from '@/workspace'

/** The copied items, shared across every bar so a group pastes into another widget.

The kind travels with them because a condition names a field of one record type, and pasted
somewhere that has no such field it would filter on nothing.
*/
let clipboard: { recordKind: RecordKind; items: FilterItem[] } | null = null

export type FilterSelection = ReturnType<typeof createFilterSelection>

/** Selection, clipboard, and structure edits over a bar's query.

Selection covers root-level items only: a block selects, moves, and copies as a unit. The
host owns the query, so every edit flows through `onUpdate` with a fresh array.
*/
export function createFilterSelection(options: {
  query: () => FilterQuery
  recordKind: () => RecordKind
  onUpdate: (query: FilterQuery) => void
}) {
  let selectedIds = $ref<ReadonlySet<string>>(new Set())
  let anchor = $ref<string | null>(null)

  // Read fresh on every use. The host's query is not always reactive, a computed here
  // would cache the first read.
  const query = () => options.query()

  function isSelected(id: string): boolean {
    return selectedIds.has(id)
  }

  function clear() {
    selectedIds = new Set()
    anchor = null
  }

  function select(id: string, mode: SelectMode = 'replace') {
    if (mode === 'replace') {
      selectedIds = new Set([id])
      anchor = id
      return
    }

    if (mode === 'toggle') {
      const next = new Set(selectedIds)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }

      selectedIds = next
      anchor = id
      return
    }

    // An extend spans the root list between the anchor and the target, falling back to a
    // plain select when the anchor is gone.
    const from = query().findIndex((item) => item.id === anchor)
    const to = query().findIndex((item) => item.id === id)
    if (from === -1 || to === -1) {
      selectedIds = new Set([id])
      anchor = id
      return
    }

    const range = query().slice(Math.min(from, to), Math.max(from, to) + 1)
    selectedIds = new Set(range.map((item) => item.id))
  }

  /** Make `id` part of the selection without disturbing one it already belongs to, the way
  a context menu targets what is under it. */
  function ensureSelected(id: string) {
    if (!selectedIds.has(id)) {
      select(id)
    }
  }

  function selectedItems(): FilterItem[] {
    return query().filter((item) => selectedIds.has(item.id))
  }

  function removeSelected() {
    if (selectedIds.size === 0) {
      return
    }

    options.onUpdate(withoutItems(query(), selectedIds))
    clear()
  }

  function copySelected() {
    const items = selectedItems()
    if (items.length > 0) {
      clipboard = { recordKind: options.recordKind(), items: structuredClone(items) }
    }
  }

  function cutSelected() {
    copySelected()
    removeSelected()
  }

  /** Where a paste with no index lands, which is before the selection so a right-click puts the
  copied items where they were aimed, and at the end with nothing selected. */
  function pasteIndex(): number {
    const first = query().findIndex((item) => selectedIds.has(item.id))
    return first === -1 ? query().length : first
  }

  /** Paste the clipboard before root index `index`, at the selection when omitted, selecting
  what was pasted. */
  function paste(index?: number) {
    if (!canPaste() || clipboard == null) {
      return
    }

    const pasted = withFreshIds(clipboard.items)
    options.onUpdate(withInserted(query(), pasted, index ?? pasteIndex()))
    selectedIds = new Set(pasted.map((item) => item.id))
    anchor = pasted[0]?.id ?? null
  }

  function canPaste(): boolean {
    return clipboard != null && clipboard.recordKind === options.recordKind()
  }

  /** Move the selection to sit before root index `index`, keeping its order. */
  function moveSelected(index: number) {
    if (selectedIds.size === 0) {
      return
    }

    options.onUpdate(withMoved(query(), selectedIds, index))
  }

  function groupSelected(op: 'and' | 'or') {
    if (selectedIds.size === 0) {
      return
    }

    const grouped = withGrouped(query(), selectedIds, op)
    options.onUpdate(grouped)
  }

  function ungroup(id: string) {
    options.onUpdate(withUngrouped(query(), id))
    clear()
  }

  return {
    selectedIds: $$(selectedIds),
    isSelected,
    select,
    ensureSelected,
    clear,
    selectedItems,
    removeSelected,
    copySelected,
    cutSelected,
    paste,
    canPaste,
    moveSelected,
    groupSelected,
    ungroup,
  }
}
