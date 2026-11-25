<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { fieldRefKey, toggleParticleField, typeRefKey } from '@/particle-series'
import type { ParticleFieldRef, ParticleTypeRef } from '@/particle-series'
import {
  connectionLabel,
  filterParticleEntries,
  particleTypeEntries,
  type ParticleTypeEntry,
  useParticleTypesByAddress,
} from '@/particle-types'
import { createRowSelection } from '@/row-selection'
import { useWorkspace } from '@/workspace'
import type { ChartWidgetParticle, SelectMode } from '@/workspace'

const {
  address: pinnedAddress,
  selectionMode = 'toggle',
  single = false,
  itemActions = false,
  frameless = false,
  collapseUnselected = false,
  maxHeight = 232,
} = defineProps<{
  /** Fixes the tree to this one address rather than a workspace's placement subtree, the
  component page's case. */
  address?: string | null
  /** Whether fields toggle into the model or select as highlighted rows for the host to act
  on through `selected`. */
  selectionMode?: 'toggle' | 'highlight'
  /** Caps the highlight selection at one field, for hosts choosing a single value. */
  single?: boolean
  /** Renders a more-actions button on each field row, wired to `itemContext` like a right
  click. */
  itemActions?: boolean
  /** Drops the tree's own frame, for a host that already draws a border around it. */
  frameless?: boolean
  /** Starts each type collapsed unless one of its fields is selected, for hosts opening onto
  an existing selection. */
  collapseUnselected?: boolean
  /** The tallest the tree grows before it scrolls, in pixels. */
  maxHeight?: number
}>()

const emit = defineEmits<{
  /** A right click landed on a field row and the selection now includes it. */
  itemContext: [event: MouseEvent, ref: ParticleFieldRef]

  /** A plain press landed on a field row, which a host may turn into a drag. */
  itemPress: [event: PointerEvent, ref: ParticleFieldRef]

  /** A right click landed on a type header row, with the selection it now acts on. */
  typeContext: [event: MouseEvent, refs: ParticleTypeRef[]]

  /** A plain press landed on a type header row, with the types a drag from it would carry. */
  typePress: [event: PointerEvent, refs: ParticleTypeRef[]]
}>()

let modelValue = $(defineModel<ChartWidgetParticle[]>({ default: () => [] }))

/** The highlight-mode selection, in the order the rows were chosen. */
let selected = $(defineModel<ParticleFieldRef[]>('selected', { default: () => [] }))

/** Remembered type expansion, shared across the tree's addresses by `address|type` key. */
let expandedTypes = $(
  defineModel<Record<string, boolean> | null>('expandedTypes', { default: null }),
)

const selectedKeys = $computed(() => new Set(selected.map(fieldRefKey)))

// Every visible field in tree order, so a shift range covers exactly the rows on screen and
// never the ones a search is hiding.
const flatOrder = $computed<ParticleFieldRef[]>(() =>
  visibleNodes.flatMap((node) => {
    const address = node.toString()
    return (filteredByAddress.get(address) ?? []).flatMap((entry) =>
      entry.fields.map((field) => ({
        address,
        type: entry.type,
        connection: entry.connection,
        field: field.name,
      })),
    )
  }),
)

// The row a shift range extends from, whichever was last chosen on its own.
let anchor = $ref<string | null>(null)

function onSelect(ref: ParticleFieldRef, mode: SelectMode) {
  const key = fieldRefKey(ref)
  typeRows.clear()

  if (single || mode === 'replace') {
    selected = [ref]
    anchor = key
    return
  }

  if (mode === 'toggle') {
    selected = selectedKeys.has(key)
      ? selected.filter((current) => fieldRefKey(current) !== key)
      : [...selected, ref]
    anchor = key
    return
  }

  const from = flatOrder.findIndex((current) => fieldRefKey(current) === anchor)
  const to = flatOrder.findIndex((current) => fieldRefKey(current) === key)
  if (from === -1 || to === -1) {
    selected = [ref]
    anchor = key
    return
  }

  selected = flatOrder.slice(Math.min(from, to), Math.max(from, to) + 1)
}

// A right click acts on the selection, so a row outside it becomes the selection first.
function onContext(ref: ParticleFieldRef, event: MouseEvent) {
  typeRows.clear()
  if (!selectedKeys.has(fieldRefKey(ref))) {
    selected = [ref]
    anchor = fieldRefKey(ref)
  }

  emit('itemContext', event, ref)
}

/** Every visible type in tree order, which is what a header range spans and the order a
selection of them reads back in. */
const typeOrder = $computed<ParticleTypeRef[]>(() =>
  visibleNodes.flatMap((node) => {
    const address = node.toString()
    return (filteredByAddress.get(address) ?? []).map((entry) => ({
      address,
      type: entry.type,
      connection: entry.connection,
    }))
  }),
)

// Held here rather than in a model, since a host acts on the types an event hands it rather than
// on a selection it has to keep.
const typeRows = createRowSelection({ ids: () => typeOrder.map(typeRefKey) })

const selectedTypeKeys = $computed(() => typeRows.selectedIds.value)

/** Drop the type header selection, the fields being held by the caller's own model. */
function clearTypeSelection() {
  typeRows.clear()
}

defineExpose({ clearTypeSelection })

function typesFor(keys: string[]): ParticleTypeRef[] {
  const wanted = new Set(keys)
  return typeOrder.filter((ref) => wanted.has(typeRefKey(ref)))
}

function onTypeSelect(ref: ParticleTypeRef, mode: SelectMode) {
  typeRows.select(typeRefKey(ref), mode)

  // The tree carries one selection, and the two act on different things, so picking a header
  // puts the fields down.
  if (selected.length > 0) {
    selected = []
  }
}

function onTypeContext(ref: ParticleTypeRef, event: MouseEvent) {
  typeRows.ensureSelected(typeRefKey(ref))
  emit('typeContext', event, typesFor(typeRows.selected()))
}

function onTypePress(ref: ParticleTypeRef, event: PointerEvent) {
  const keys = typeRows.pressTargets(typeRefKey(ref), event)
  if (keys != null) {
    emit('typePress', event, typesFor(keys))
  }
}

const engine = useEngine()

// Not called when the address is pinned since the component page hosts this outside any
// workspace's own tree.
const workspace = pinnedAddress == null ? useWorkspace() : null

const addressNodes = $computed<Address[]>(() => {
  if (pinnedAddress != null) {
    try {
      return [Address.parse(pinnedAddress)]
    } catch {
      return []
    }
  }

  const all = engine.components.all.map((component) => component.address)
  const scope = workspace?.scope ?? null
  if (scope == null || scope.isEngine) {
    return all
  }

  const base = scope.toString()
  return all.filter((address) => {
    const value = address.toString()
    return value === base || value.startsWith(`${base}.`)
  })
})

/** What the search input holds, matched case-insensitively across the tree. */
let filter = $ref<string>('')

const normalizedFilter = $computed(() => filter.trim().toLowerCase())

const declaredByAddress = $(
  useParticleTypesByAddress(() => addressNodes.map((node) => node.toString())).types,
)

const entriesByAddress = $computed<Map<string, ParticleTypeEntry[]>>(
  () =>
    new Map(
      [...declaredByAddress].map(([address, types]) => [
        address,
        particleTypeEntries(types, (name) => connectionLabel(engine, address, name)),
      ]),
    ),
)

// Filtered once for the whole tree, deciding address visibility here and handed down as each
// child's rows.
const filteredByAddress = $computed<Map<string, ParticleTypeEntry[]>>(
  () =>
    new Map(
      [...entriesByAddress].map(([address, entries]) => [
        address,
        filterParticleEntries(address, entries, normalizedFilter),
      ]),
    ),
)

// Addresses declaring nothing sink to the bottom since they offer nothing to pick, and a
// search drops them along with everything else it does not match.
const visibleNodes = $computed<Address[]>(() => {
  const declaring = addressNodes.filter(
    (node) => (declaredByAddress.get(node.toString())?.length ?? 0) > 0,
  )
  if (normalizedFilter === '') {
    const empty = addressNodes.filter(
      (node) => (declaredByAddress.get(node.toString())?.length ?? 0) === 0,
    )
    return [...declaring, ...empty]
  }

  return declaring.filter((node) => (filteredByAddress.get(node.toString())?.length ?? 0) > 0)
})

function toggleField(ref: ParticleFieldRef, value: boolean) {
  modelValue = toggleParticleField(modelValue, ref, value)
}
</script>

<template>
  <div>
    <div :class="!frameless && 'border-default rounded-md border'">
      <div class="flex items-center gap-2 px-2">
        <c-icon class="text-muted shrink-0" :name="icons.search" size="14" />
        <input
          v-model="filter"
          class="h-7 w-full bg-transparent text-xs outline-none"
          placeholder="Search"
          spellcheck="false"
          type="text"
        />
        <c-button
          v-if="filter !== ''"
          color="neutral"
          :icon="icons.clear"
          size="xs"
          square
          variant="ghost"
          @click="filter = ''"
        />
      </div>
      <c-separator />
      <div class="overflow-y-auto py-1" :style="{ maxHeight: `${maxHeight}px` }">
        <div v-if="addressNodes.length === 0" class="px-2 py-1">
          <c-text variant="description">No components in this scope.</c-text>
        </div>
        <div v-else-if="visibleNodes.length === 0" class="px-2 py-1">
          <c-text variant="description">No matching fields.</c-text>
        </div>
        <c-particle-data-picker-address
          v-for="node in visibleNodes"
          :key="node.toString()"
          v-model:expanded-types="expandedTypes"
          :address="node"
          :bare="addressNodes.length === 1"
          :collapse-unselected="collapseUnselected"
          :filter="normalizedFilter"
          :item-actions="itemActions"
          :particles="modelValue"
          :selected-keys="selectedKeys"
          :selected-type-keys="selectedTypeKeys"
          :selection-mode="selectionMode"
          :shown-types="filteredByAddress.get(node.toString()) ?? []"
          @context="onContext"
          @press="(ref, event) => emit('itemPress', event, ref)"
          @select="onSelect"
          @toggle="toggleField"
          @type-context="onTypeContext"
          @type-press="onTypePress"
          @type-select="onTypeSelect"
        />
      </div>
    </div>
  </div>
</template>
