<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'

import { Address } from '@/api/address'
import type { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { defaultSeriesColor } from '@/chart'
import icons from '@/icons'
import {
  addParticleSeries,
  duplicateParticleGroup,
  fieldRefKey,
  groupConnection,
  removeParticleSeries,
  toggleParticleField,
  withGroupConnection,
} from '@/particle-series'
import type { ParticleFieldRef } from '@/particle-series'
import { filterParticleTypes, useParticleTypesByAddress } from '@/particle-types'
import { ChartWidgetSeriesModel, useWorkspace } from '@/workspace'
import type { ChartWidgetParticle, ChartWidgetSeries, SelectMode } from '@/workspace'

const {
  address: pinnedAddress,
  showSelected = false,
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
  /** Whether the "Series" section renders below the tree. Requires a
  workspace context so only a host without a pinned address sets this. */
  showSelected?: boolean
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
    return (filteredByAddress.get(address) ?? []).flatMap((type) =>
      type.fields.map((field) => ({ address, type: type.type, field: field.name })),
    )
  }),
)

// The row a shift range extends from, whichever was last chosen on its own.
let anchor = $ref<string | null>(null)

function onSelect(address: string, type: string, field: string, mode: SelectMode) {
  const ref: ParticleFieldRef = { address, type, field }
  const key = fieldRefKey(ref)

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
function onContext(address: string, type: string, field: string, event: MouseEvent) {
  const ref: ParticleFieldRef = { address, type, field }
  if (!selectedKeys.has(fieldRefKey(ref))) {
    selected = [ref]
    anchor = fieldRefKey(ref)
  }

  emit('itemContext', event, ref)
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

// Filtered once for the whole tree, deciding address visibility here and handed down as each
// child's rows. An address whose own name matches keeps everything under it.
const filteredByAddress = $computed<Map<string, ParticleTypeInfo[]>>(() => {
  const map = new Map<string, ParticleTypeInfo[]>()
  for (const [address, types] of declaredByAddress) {
    const effective = address.toLowerCase().includes(normalizedFilter) ? '' : normalizedFilter
    map.set(address, filterParticleTypes(types, effective))
  }

  return map
})

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

function toggleField(address: string, type: string, field: string, value: boolean) {
  modelValue = toggleParticleField(modelValue, address, type, field, value)
}

type SelectedTypeGroup = {
  type: string
  connection: string | null
  /** Where the group sits in the model, for the actions that act on the whole group. */
  index: number
  series: ChartWidgetSeries[]
  warning: string | null
}
type SelectedAddressGroup = { address: string; types: SelectedTypeGroup[] }

/** Why a stored series names something the components do not declare, if it does.

A driver rename leaves the series behind pointing at a type nothing produces, and the chart
then draws an empty plot with nothing on screen saying why.
*/
function seriesWarning(address: string, type: string): string | null {
  // Nothing is known before the component list lands, which is not the same as nothing existing.
  if (engine.components.all.length === 0) {
    return null
  }

  const declared = declaredByAddress.get(address)
  if (declared == null) {
    return `No component at ${address} in this scope.`
  }

  if (!declared.some((current) => current.type === type)) {
    return `${address} declares no particle type "${type}".`
  }

  return null
}

// Grouped for display under the same address/type hierarchy the tree uses, merging any stored
// entries that happen to share an address and type rather than assuming one entry per pair.
const selectedGroups = $computed<SelectedAddressGroup[]>(() => {
  const byAddress = new Map<string, Map<string, SelectedTypeGroup>>()

  for (const [index, particle] of modelValue.entries()) {
    const address = particle.address?.toString() ?? '(no address)'
    const type = particle.type ?? '(no type)'
    const connection = groupConnection(particle)
    const byType = byAddress.get(address) ?? new Map<string, SelectedTypeGroup>()

    // Narrowing to a connection is what separates two groups of the same type, so it belongs
    // in the key rather than merging them back into one row.
    const key = `${type}|${connection ?? ''}`
    const existing = byType.get(key)
    byType.set(key, {
      type,
      connection,
      index: existing?.index ?? index,
      series: [...(existing?.series ?? []), ...particle.series],
      warning: seriesWarning(address, type),
    })
    byAddress.set(address, byType)
  }

  return [...byAddress.entries()].map(([address, byType]) => ({
    address,
    types: [...byType.values()],
  }))
})

/** The connections a group's type can narrow to.

The type's declared connections are the ones its records carry, so they are the whole
useful list. A type declaring none is unattributed and falls back to every connection the
component has, which at least bounds the choice.
*/
function connectionsFor(group: SelectedTypeGroup, address: string): string[] {
  const declared = declaredByAddress
    .get(address)
    ?.find((current) => current.type === group.type)?.connections
  if (declared != null && declared.length > 0) {
    return [...declared]
  }

  return (engine.components.get(address)?.connections ?? []).map((connection) => connection.name)
}

function connectionItems(group: SelectedTypeGroup, address: string): DropdownMenuItem[][] {
  const every = {
    label: 'Every Connection',
    type: 'checkbox' as const,
    checked: group.connection == null,
    onSelect: () => (modelValue = withGroupConnection(modelValue, group.index, null)),
  }

  // A stored connection the list no longer carries still shows as itself.
  const names = connectionsFor(group, address)
  if (group.connection != null && !names.includes(group.connection)) {
    names.push(group.connection)
  }

  const declared = names.map((connection) => ({
    label: connection,
    type: 'checkbox' as const,
    checked: group.connection === connection,
    onSelect: () => (modelValue = withGroupConnection(modelValue, group.index, connection)),
  }))

  return [[every], declared].filter((entries) => entries.length > 0)
}

function groupItems(group: SelectedTypeGroup): DropdownMenuItem[] {
  return [
    {
      label: 'Duplicate Group',
      icon: icons.duplicate,
      onSelect: () => (modelValue = duplicateParticleGroup(modelValue, group.index)),
    },
  ]
}

// What the chart draws this series in. A widget stored before series carried a color has none to
// show, and the swatch must still stand for the line it edits.
function colorOf(series: ChartWidgetSeries): string {
  if (series.color != null) {
    return series.color
  }

  const drawn = modelValue.flatMap((particle) => particle.series)
  return defaultSeriesColor(Math.max(0, drawn.indexOf(series)))
}

function removeSeries(seriesId: string) {
  modelValue = removeParticleSeries(modelValue, seriesId)
}

let isManualEntryOpen = $ref(false)
let manualAddress = $ref<string | null>(null)
let manualType = $ref<string | null>(null)
let manualField = $ref<string | null>(null)
let manualLabel = $ref<string>('')

const manualResolvedAddress = $computed(
  () => workspace?.resolveAddress(manualAddress)?.toString() ?? manualAddress,
)

/** Add a manual entry for an undeclared type or field, merging into an existing address and
type entry the way a toggle does. Only the field and label reset. */
function addManualEntry() {
  if (manualAddress == null || manualType == null || manualField == null) {
    return
  }

  const address = manualResolvedAddress
  if (address == null) {
    return
  }

  const series = ChartWidgetSeriesModel.parse({ field: manualField, label: manualLabel || null })
  modelValue = addParticleSeries(modelValue, address, manualType, series)
  manualField = null
  manualLabel = ''
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
        <c-particle-series-selector-address
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
          :selection-mode="selectionMode"
          :shown-types="filteredByAddress.get(node.toString()) ?? []"
          @context="(type, field, event) => onContext(node.toString(), type, field, event)"
          @press="
            (type, field, event) =>
              emit('itemPress', event, { address: node.toString(), type, field })
          "
          @select="(type, field, mode) => onSelect(node.toString(), type, field, mode)"
          @toggle="(type, field, value) => toggleField(node.toString(), type, field, value)"
        />
      </div>
    </div>

    <template v-if="showSelected">
      <div class="mt-4 pb-1">
        <c-text variant="title2">Series</c-text>
      </div>
      <div class="border-default rounded-md border pb-1">
        <div v-if="selectedGroups.length === 0" class="px-2 py-1">
          <c-text variant="description">No particle series selected.</c-text>
        </div>
        <template v-for="group in selectedGroups" :key="group.address">
          <template
            v-for="typeGroup in group.types"
            :key="`${group.address}|${typeGroup.type}|${typeGroup.connection ?? ''}`"
          >
            <!-- The established path notation, one line standing in for the address and type
            levels. -->
            <div class="flex items-center gap-1.5 px-2 py-1">
              <c-text variant="mono-sm">
                {{ group.address }}::particles::{{ typeGroup.type }}
              </c-text>
              <c-tooltip v-if="typeGroup.warning != null" :text="typeGroup.warning">
                <c-icon class="text-warning shrink-0" :name="icons.warning" size="14" />
              </c-tooltip>
              <div class="grow" />
              <!-- Narrowing to a connection is the rare case, so unset it is an icon and only a
              chosen connection takes the room to name itself. -->
              <c-dropdown-menu
                :items="connectionItems(typeGroup, group.address)"
                size="sm"
                :ui="{ content: 'w-auto min-w-fit' }"
              >
                <c-tooltip :text="typeGroup.connection == null ? 'Every Connection' : 'Connection'">
                  <c-button
                    :color="typeGroup.connection == null ? 'neutral' : 'primary'"
                    :icon="icons.connection"
                    :label="typeGroup.connection ?? undefined"
                    size="xs"
                    :square="typeGroup.connection == null"
                    :ui="{ label: 'font-mono text-[10px]' }"
                    variant="ghost"
                  />
                </c-tooltip>
              </c-dropdown-menu>
              <c-dropdown-menu :items="groupItems(typeGroup)" size="sm">
                <c-button color="neutral" :icon="icons.more" size="xs" square variant="ghost" />
              </c-dropdown-menu>
            </div>
            <div
              v-for="series in typeGroup.series"
              :key="series.id"
              class="flex min-h-6 items-center gap-2 py-0.5 pl-5"
            >
              <span class="min-w-40 font-mono text-[11px]">{{ series.field }}</span>
              <input
                v-model="series.label"
                :class="[
                  'border-default focus:border-primary w-45 rounded-sm border',
                  'bg-transparent px-1.5 py-0.5 text-xs outline-none',
                ]"
                placeholder="Label"
                spellcheck="false"
                type="text"
              />
              <c-tooltip text="Series Color">
                <c-color-input
                  :model-value="colorOf(series)"
                  @update:model-value="series.color = $event"
                />
              </c-tooltip>
              <c-button
                color="neutral"
                :icon="icons.cancel"
                size="xs"
                square
                variant="ghost"
                @click="removeSeries(series.id)"
              />
            </div>
          </template>
        </template>
      </div>

      <!-- Collapsed by default since manual entry is the fallback for undeclared fields. -->
      <div class="border-default mt-4 mb-4 rounded-md border">
        <button
          class="hover:bg-elevated/50 flex w-full items-center gap-1 px-2 py-0.5 text-left"
          type="button"
          @click="isManualEntryOpen = !isManualEntryOpen"
        >
          <c-icon
            class="text-muted shrink-0 transition-transform"
            :class="isManualEntryOpen && 'rotate-90'"
            :name="icons.chevronRight"
            size="12"
          />
          <c-text variant="title3">Manual Entry</c-text>
        </button>
        <div v-if="isManualEntryOpen" class="flex flex-col gap-2 p-2 pt-3">
          <c-workspace-address-select v-model="manualAddress" />
          <c-particle-type-select v-model="manualType" :address="manualResolvedAddress" />
          <div class="flex items-end gap-2">
            <c-particle-field-select
              v-model="manualField"
              :address="manualResolvedAddress"
              class="flex-1"
              :particle-type="manualType"
            />
            <c-input
              v-model="manualLabel"
              class="flex-1"
              placeholder="Label"
              size="sm"
              spellcheck="false"
            />
            <c-schema-form-node-add-button @click="addManualEntry" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
