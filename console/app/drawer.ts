import { defineStore } from 'pinia'
import { computed } from 'vue'

import { AddressModel } from '@/api/address'
import { usePersisted } from '@/persistence'

/** Geometry of the component tree's indent columns.

Shared because the tree hangs off the header above it, which has to know where column zero runs in
order to drop a line into it. The step can be no narrower than the toggle, since a toggle sits in
its own column and the line down the column before it has to pass without touching.
*/
const treeColumnStep = 12
export const treeToggleWidth = 14
/** Column zero, set to the middle of the header's own icon so the tree hangs off it squarely.

A pixel left of that middle rather than on it, because a one pixel line covers the pixel after its
position. Placed on the middle exactly, the line would sit half a pixel to the right of the icon it
hangs from.
*/
const treeRootColumn = 20

/** Diameter of the ring drawn around a toggle, which the lines reaching it stop at. */
export const treeNodeSize = 16

/** The middle of a column, counting the header's own as zero. */
export function treeColumnCenter(column: number): number {
  return treeRootColumn + treeColumnStep * column
}

/** Where a row's own column begins, which is where its toggle and everything after it start. */
export function treeColumnStart(column: number): number {
  return treeColumnCenter(column) - treeToggleWidth / 2
}

export const useDrawer = defineStore('drawer', () => {
  const state = usePersisted({
    schema: ({ object, array, number, boolean }) =>
      object({
        width: number().default(300),
        isOpen: boolean().default(true),
        collapsed: array(AddressModel).default(() => []),
      }),
    methods: [{ type: 'local-storage', key: ['store', 'drawer'] }],
  })

  return {
    width: computed({
      get: () => state.width,
      set: (value) => (state.width = value),
    }),
    isOpen: computed({
      get: () => state.isOpen,
      set: (value) => (state.isOpen = value),
    }),
    collapsed: computed({
      get: () => state.collapsed,
      set: (value) => (state.collapsed = value),
    }),
    toggle: () => (state.isOpen = !state.isOpen),
  }
})

/** Whether `open` is `own` or sits somewhere below it.

The whole branch down to the open component is drawn stronger, so every row on the way has to
recognize itself. The separator guards against a sibling whose name merely starts the same way.
*/
export function isOnPathTo(open: string | null, own: string): boolean {
  return open != null && (open === own || open.startsWith(`${own}.`))
}
