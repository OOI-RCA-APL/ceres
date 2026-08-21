import { onClickOutside } from '@vueuse/core'
import type { MaybeRefOrGetter } from 'vue'

import type { SelectMode } from '@/workspace'

/** Drop the selection when a press lands away from `container`.

A menu or dialog is drawn at the far end of the page while acting on the selection it was opened
over, so a press inside one is left alone.
*/
export function clearOnOutsidePress(
  container: MaybeRefOrGetter<HTMLElement | null | undefined>,
  clear: () => void,
) {
  onClickOutside(container, clear, { ignore: ['[role="menu"]', '[role="dialog"]'] })
}

/** The select mode a click's modifiers ask for, matching the workspace's own vocabulary. */
export function selectMode(event: MouseEvent): SelectMode {
  if (event.shiftKey) {
    return 'extend'
  }

  return event.metaKey || event.ctrlKey ? 'toggle' : 'replace'
}

/** Whether a press is the plain one a drag may start from. A modified press is a selection
gesture, and a press of any other button belongs to the menu it opens. */
export function isPlainPress(event: PointerEvent): boolean {
  return event.button === 0 && !event.shiftKey && !event.metaKey && !event.ctrlKey
}

export type RowSelection = ReturnType<typeof createRowSelection>

/** Highlight selection over an ordered list of row IDs.

Shared by every list whose rows are picked, right clicked, and dragged into a workspace. `ids`
is read on every use rather than cached, so a range covers the rows as they stand.
*/
export function createRowSelection(options: { ids: () => string[] }) {
  let selectedIds = $ref<ReadonlySet<string>>(new Set())

  /** The row an extend spans from, whichever was last chosen on its own. */
  let anchor = $ref<string | null>(null)

  const ids = () => options.ids()

  function isSelected(id: string): boolean {
    return selectedIds.has(id)
  }

  /** The selection in row order, which is the order the rows were drawn in rather than the
  order they were chosen. */
  function selected(): string[] {
    return ids().filter((id) => selectedIds.has(id))
  }

  function clear() {
    selectedIds = new Set()
    anchor = null
  }

  /** Take `next` as the whole selection, anchored on its first row. */
  function replace(next: readonly string[]) {
    selectedIds = new Set(next)
    anchor = next[0] ?? null
  }

  function select(id: string, mode: SelectMode = 'replace') {
    if (mode === 'replace') {
      replace([id])
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

    // An extend spans the rows between the anchor and the target, falling back to a plain
    // select when the anchor is gone.
    const order = ids()
    const from = order.indexOf(anchor ?? '')
    const to = order.indexOf(id)
    if (from === -1 || to === -1) {
      replace([id])
      return
    }

    selectedIds = new Set(order.slice(Math.min(from, to), Math.max(from, to) + 1))
  }

  /** Make `id` part of the selection without disturbing one it already belongs to, the way a
  context menu targets what is under it. */
  function ensureSelected(id: string) {
    if (!selectedIds.has(id)) {
      select(id)
    }
  }

  function onClick(id: string, event: MouseEvent) {
    select(id, selectMode(event))
  }

  /** The rows a drag started on `id` carries, or null for a press that is not one.

  A press inside the selection takes the whole of it, and one outside takes the row alone
  without disturbing what is selected, the same rule the context menu applies.
  */
  function pressTargets(id: string, event: PointerEvent): string[] | null {
    if (!isPlainPress(event)) {
      return null
    }

    return isSelected(id) ? selected() : [id]
  }

  return {
    selectedIds: $$(selectedIds),
    isSelected,
    selected,
    select,
    replace,
    ensureSelected,
    clear,
    onClick,
    pressTargets,
  }
}
