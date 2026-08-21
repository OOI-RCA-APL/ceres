<script lang="ts" setup generic="T">
import type { ContextMenuItem } from '@nuxt/ui'

import { createRowSelection } from '@/row-selection'
import type { Widget, WidgetPlacement } from '@/workspace'

/** One thing a selection of rows can be turned into.

`separate` is given only where it differs from `combined`, which is what decides whether the
per-row form is offered at all.
*/
export type DetailWidgetAction<T> = {
  label: string
  /** How the per-row form is named, required wherever `separate` is given. */
  separateLabel?: string
  icon: string
  combined: (items: T[]) => Widget[]
  separate?: (items: T[]) => Widget[]
}

const {
  items,
  keyOf,
  actions,
  title,
  empty,
  disabled = null,
  insertDrag = null,
  insertAt = null,
} = defineProps<{
  items: readonly T[]
  /** What a row is tracked by, unique within this list. */
  keyOf: (item: T) => string
  /** What the rows can become, in the order the menu offers them. */
  actions: DetailWidgetAction<T>[]
  title: string
  /** What stands in for an empty list. */
  empty: string
  /** Rows that cannot be selected, so nothing is built from what the user cannot reach. */
  disabled?: ((item: T) => boolean) | null

  /** Starts a workspace insertion drag on a pressed row, handed down by a page hosting a
  workspace. Absent, rows offer no drag. */
  insertDrag?:
    ((widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) => void) | null

  /** Inserts widgets where an insertion drag landed. */
  insertAt?: ((widgets: Widget[], placement: WidgetPlacement) => void) | null
}>()

const emit = defineEmits<{
  /** Widgets built from the selected rows, for the caller to land on its workspace. */
  create: [widgets: Widget[]]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

const selectable = $computed(() => items.filter((item) => disabled?.(item) !== true))

const rows = createRowSelection({ ids: () => selectable.map(keyOf) })

function itemsFor(keys: string[]): T[] {
  const wanted = new Set(keys)
  return selectable.filter((item) => wanted.has(keyOf(item)))
}

/** Every way the given rows can be built, the combined form of each action first and the
per-row form beside it wherever several rows make that a different result. */
function choicesFor(keys: string[]): { label: string; icon: string; widgets: () => Widget[] }[] {
  const chosen = itemsFor(keys)
  return actions.flatMap((action) => {
    const combined = {
      label: action.label,
      icon: action.icon,
      widgets: () => action.combined(chosen),
    }
    if (action.separate == null || action.separateLabel == null || chosen.length < 2) {
      return [combined]
    }

    return [
      combined,
      {
        label: action.separateLabel,
        icon: action.icon,
        widgets: () => action.separate?.(chosen) ?? [],
      },
    ]
  })
}

const menuItems = $computed<ContextMenuItem[][]>(() => {
  const keys = rows.selected()
  return [
    choicesFor(keys).map((choice) => ({
      label: choice.label,
      icon: choice.icon,
      disabled: keys.length === 0,
      onSelect: () => emit('create', choice.widgets()),
    })),
  ]
})

// Every item here acts on the selection, so a right click that cannot reach it is defaulted and
// the menu's trigger leaves it alone. A blocked row counts as elsewhere, or the menu would open
// over it offering to build from whatever was selected before.
function onListContext(event: MouseEvent) {
  const row = (event.target as HTMLElement).closest('[data-detail-row]')
  if (row == null || row.hasAttribute('data-detail-blocked')) {
    event.preventDefault()
  }
}

/** A drop waiting on the what-to-create prompt, with the rows that were dragged. */
let pendingDrop = $ref<{ placement: WidgetPlacement; keys: string[] } | null>(null)

const pendingChoices = $computed(() => (pendingDrop == null ? [] : choicesFor(pendingDrop.keys)))

/** What a row listens for, which a blocked row is given none of, so it stays the plain
undecorated element it was before any of this could be built from it. */
function handlersFor(item: T) {
  if (disabled?.(item) === true) {
    return {}
  }

  return {
    click: (event: MouseEvent) => rows.onClick(keyOf(item), event),
    contextmenu: () => rows.ensureSelected(keyOf(item)),
    // A shift click extends the selection, and the browser would otherwise take it as a text
    // selection across the rows it spans.
    mousedown: (event: MouseEvent) => event.shiftKey && event.preventDefault(),
    pointerdown: (event: PointerEvent) => onRowPress(item, event),
  }
}

function onRowPress(item: T, event: PointerEvent) {
  if (insertDrag == null || insertAt == null) {
    return
  }

  const keys = rows.pressTargets(keyOf(item), event)
  if (keys == null) {
    return
  }

  // The first action's widgets stand in for the preview, the choice of what to create being
  // asked on release.
  const preview = choicesFor(keys)[0]?.widgets() ?? []
  if (preview.length === 0) {
    return
  }

  insertDrag(preview, (placement) => {
    if (placement == null) {
      return
    }

    // A drop with one way to read it needs nothing asked of it.
    const choices = choicesFor(keys)
    if (choices.length === 1) {
      insertAt?.(choices[0]?.widgets() ?? [], placement)
      return
    }

    pendingDrop = { placement, keys }
  })
}

function drop(widgets: Widget[]) {
  if (pendingDrop == null) {
    return
  }

  insertAt?.(widgets, pendingDrop.placement)
  pendingDrop = null
}
</script>

<!-- One expandable detail list whose rows are selected, right clicked, and dragged into a
workspace to build widgets from what they name. -->
<template>
  <!-- Rendered without a wrapper, since a list rounds its first and last sections into its own
  corners and an element between them would take that rounding instead. -->
  <c-detail-section v-model:expanded="expanded" :title="`${title} (${items.length})`">
    <c-context-menu :items="menuItems">
      <div @contextmenu="onListContext">
        <c-text v-if="items.length === 0" class="px-3" variant="description">{{ empty }}</c-text>
        <c-list-item
          v-for="item in items"
          :key="keyOf(item)"
          :class="
            // Neutral rather than a semantic color, so the highlight never fights the text.
            rows.isSelected(keyOf(item)) && 'bg-[#80808029]'
          "
          :data-detail-blocked="disabled?.(item) === true ? '' : undefined"
          data-detail-row
          :selectable="disabled?.(item) !== true"
          v-on="handlersFor(item)"
        >
          <slot :item="item" name="row" />
        </c-list-item>
      </div>
    </c-context-menu>

    <!-- What dragged rows become is only asked once they land, the same rows reading as more
    than one arrangement of widgets. -->
    <c-modal
      :open="pendingDrop != null"
      title="Add Widgets"
      @update:open="(value: boolean) => !value && (pendingDrop = null)"
    >
      <template #body>
        <div class="flex min-w-56 flex-col gap-1">
          <c-button
            v-for="choice in pendingChoices"
            :key="choice.label"
            block
            color="neutral"
            :icon="choice.icon"
            :label="choice.label"
            :ui="{ label: 'grow text-left' }"
            variant="ghost"
            @click="drop(choice.widgets())"
          />
        </div>
      </template>
    </c-modal>
  </c-detail-section>
</template>
