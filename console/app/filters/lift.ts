import type { InjectionKey } from 'vue'

/** How a condition nested in a block is dragged out of it.

The root conditions reorder against each other, and a nested one has no siblings out there to
slide along, so it is carried on its own and lands wherever the root list is released over.
*/
export type FilterLift = {
  /** The listeners a nested chip binds with `v-on`, keyed by event name as that syntax expects. */
  handlers: (id: string) => Record<string, (event: PointerEvent) => void>

  /** Where the chip is drawn while it is being carried. */
  styleFor: (id: string) => Record<string, string> | undefined
}

export const filterLiftKey: InjectionKey<FilterLift> = Symbol('filter-lift')
