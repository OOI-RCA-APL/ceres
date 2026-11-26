<script lang="ts" setup>
import { createReusableTemplate } from '@vueuse/core'
import { watch } from 'vue'

import type { Address } from '@/api/address'
import type { ParticleFieldInfo } from '@/api/components'
import type { ParticleFieldDetails } from '@/components/c-particle-field-details-dialog.vue'
import icons from '@/icons'
import { fieldRefKey, groupConnection, typeRefKey } from '@/particle-series'
import type { ParticleFieldRef, ParticleTypeRef } from '@/particle-series'
import {
  describeFieldDescription,
  describeFieldType,
  describeParticleTypeEntry,
  type ParticleTypeEntry,
} from '@/particle-types'
import { isPlainPress, selectMode } from '@/row-selection'
import type { Schema } from '@/schema-form'
import type { ChartWidgetParticle, SelectMode } from '@/workspace'

const {
  address,
  particles = [],
  selectionMode = 'toggle',
  selectedKeys = new Set<string>(),
  selectedTypeKeys = new Set<string>(),
  itemActions = false,
  bare = false,
  defaultOpened = false,
  collapseUnselected = false,
  filter = '',
  shownTypes,
} = defineProps<{
  address: Address

  /** The rows to render, the address's catalog entries as the host's search narrowed them. */
  shownTypes: ParticleTypeEntry[]

  /** The chart model's particle entries, read in toggle mode to mark which fields are on. */
  particles?: ChartWidgetParticle[]

  /** Whether fields toggle with checkboxes or select as highlighted rows. */
  selectionMode?: 'toggle' | 'highlight'

  /** The selection in highlight mode, as `fieldRefKey` keys spanning the whole tree. */
  selectedKeys?: Set<string>

  /** The selected type headers, as `typeRefKey` keys spanning the whole tree. */
  selectedTypeKeys?: ReadonlySet<string>

  /** Renders a more-actions button on each field row, sharing the `context` event with
  right clicks. */
  itemActions?: boolean

  /** Renders the types directly without the address header, for a tree of one address where
  the level would only repeat the page. */
  bare?: boolean

  defaultOpened?: boolean

  /** Starts a type collapsed unless one of its fields is selected, for hosts opening onto an
  existing selection. */
  collapseUnselected?: boolean

  /** A lowercased search string narrowing the types and fields shown. Matching the address
  itself shows everything under it. */
  filter?: string
}>()

/** Remembered type expansion by `typeRefKey` key, for hosts that persist the tree between
visits. Entries without a key fall back to the default. */
let expandedTypes = $(
  defineModel<Record<string, boolean> | null>('expandedTypes', { default: null }),
)

function typeRef(entry: ParticleTypeEntry): ParticleTypeRef {
  return { address: address.toString(), type: entry.type, connection: entry.connection }
}

function fieldRef(entry: ParticleTypeEntry, field: string): ParticleFieldRef {
  return { ...typeRef(entry), field }
}

function isTypeOpened(entry: ParticleTypeEntry): boolean {
  // A search reaches into every type whether or not it was opened.
  if (effectiveFilter !== '') {
    return true
  }

  const key = typeRefKey(typeRef(entry))
  const remembered = expandedTypes?.[key] ?? localOpen[key]
  if (remembered != null) {
    return remembered
  }

  return !collapseUnselected || typeHasSelection(entry)
}

// Toggles made by hosts that do not persist expansion still hold for this mount.
const localOpen = $ref<Record<string, boolean>>({})

// A plain click on a header expands it, the tree's first purpose. Held modifiers ask for the
// header itself instead, which is the same vocabulary the field rows answer to.
function onTypeClick(entry: ParticleTypeEntry, event: MouseEvent) {
  const mode = selectionMode === 'highlight' ? selectMode(event) : 'replace'
  if (mode === 'replace') {
    toggleType(entry, event)
    return
  }

  emit('typeSelect', typeRef(entry), mode)
}

function toggleType(entry: ParticleTypeEntry, event: MouseEvent) {
  // A press the pointer travelled from was a drag, and its release still reaches the header as
  // a click, which would collapse the type the widget was just dragged out of.
  if (travelled(event)) {
    return
  }

  const value = !isTypeOpened(entry)

  // A toggle while a search is forcing everything open would be forgotten anyway.
  if (effectiveFilter !== '') {
    return
  }

  const key = typeRefKey(typeRef(entry))
  localOpen[key] = value
  if (expandedTypes != null) {
    expandedTypes = { ...expandedTypes, [key]: value }
  }
}

const emit = defineEmits<{
  /** A field's toggle changed. */
  toggle: [ref: ParticleFieldRef, value: boolean]

  /** A highlight-mode click, with the select mode the held modifiers ask for. */
  select: [ref: ParticleFieldRef, mode: SelectMode]

  /** A right click on a field row, before the hosting menu opens on the event. */
  context: [ref: ParticleFieldRef, event: MouseEvent]

  /** A plain press on a field row in highlight mode, which a host may turn into a drag. */
  press: [ref: ParticleFieldRef, event: PointerEvent]

  /** A modifier click on a type header row, which selects rather than expanding it. */
  typeSelect: [ref: ParticleTypeRef, mode: SelectMode]

  /** A right click on a type header row, before the hosting menu opens on the event. */
  typeContext: [ref: ParticleTypeRef, event: MouseEvent]

  /** A plain press on a type header row, which a host may turn into a drag. */
  typePress: [ref: ParticleTypeRef, event: PointerEvent]
}>()

// The type list renders inside the address expansion item, or on its own in bare mode.
const [DefineTypeList, ReuseTypeList] = createReusableTemplate()

let expanded = $ref(defaultOpened || bare)

const types = $computed(() => shownTypes)

// The address's own name matching is as good as every type matching, so the filter stops
// narrowing below it.
const effectiveFilter = $computed(() =>
  address.toString().toLowerCase().includes(filter) ? '' : filter,
)

// A search reaches into addresses whether or not they were opened, so typing one opens them,
// and clearing it restores whatever the user had arranged.
let expandedBeforeSearch: boolean | null = null

watch(
  () => filter,
  (value, previous) => {
    if (value !== '' && previous === '') {
      expandedBeforeSearch = expanded
      expanded = true
    } else if (value === '' && expandedBeforeSearch != null) {
      expanded = expandedBeforeSearch
      expandedBeforeSearch = null
    }
  },
)

// Toggle mode reads the model through one key set rather than rebuilding series per field row.
const onFieldKeys = $computed(() => {
  const keys = new Set<string>()
  const base = address.toString()
  for (const particle of particles) {
    if ((particle.address?.toString() ?? null) !== base || particle.type == null) {
      continue
    }

    for (const series of particle.series) {
      if (series.field != null) {
        keys.add(
          fieldRefKey({
            address: base,
            type: particle.type,
            connection: groupConnection(particle),
            field: series.field,
          }),
        )
      }
    }
  }

  return keys
})

function isFieldOn(entry: ParticleTypeEntry, field: string): boolean {
  const key = fieldRefKey(fieldRef(entry, field))
  return selectionMode === 'highlight' ? selectedKeys.has(key) : onFieldKeys.has(key)
}

function typeHasSelection(entry: ParticleTypeEntry): boolean {
  return entry.fields.some((field) => isFieldOn(entry, field.name))
}

function isTypeSelected(entry: ParticleTypeEntry): boolean {
  return selectedTypeKeys.has(typeRefKey(typeRef(entry)))
}

// Read against every declared type rather than the filtered view so a selection hidden by a
// search still marks its containers.
const addressHasSelection = $computed(() => types.some(typeHasSelection))

/** The field whose details dialog is showing. */
let detailsField = $ref<ParticleFieldDetails | null>(null)

// A highlight click is a selection, so there the details dialog moves to double click. In
// toggle mode the checkbox already carries the choice and a single click opens it.
function onClick(entry: ParticleTypeEntry, field: ParticleFieldInfo, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('select', fieldRef(entry, field.name), selectMode(event))
  } else {
    detailsField = { address: address.toString(), type: entry.type, field }
  }
}

function onDoubleClick(entry: ParticleTypeEntry, field: ParticleFieldInfo) {
  if (selectionMode === 'highlight') {
    detailsField = { address: address.toString(), type: entry.type, field }
  }
}

// Never prevent the default here. A wrapping context menu opens only on an event nothing has
// defaulted, and it suppresses the native menu itself.
function onContext(entry: ParticleTypeEntry, field: string, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('context', fieldRef(entry, field), event)
  }
}

// A context menu opens on a context menu event alone, so the button raises one at its own
// corner rather than the row carrying a second copy of the host's items.
function onActions(event: MouseEvent) {
  ;(event.target as HTMLElement).dispatchEvent(
    new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      clientX: event.clientX,
      clientY: event.clientY,
    }),
  )
}

// Only a plain press is offered as a drag. A modified press is a selection gesture, and the
// click that follows an untravelled press still selects as it always did.
function onPointerDown(entry: ParticleTypeEntry, field: string, event: PointerEvent) {
  if (selectionMode !== 'highlight' || !isPlainPress(event)) {
    return
  }

  emit('press', fieldRef(entry, field), event)
}

/** Where the last press landed, for telling a click apart from a drag's release. Cleared by
every press so one gesture never answers for the next. */
let pressPoint: { x: number; y: number } | null = null

function onTypePointerDown(entry: ParticleTypeEntry, event: PointerEvent) {
  pressPoint = null
  if (selectionMode !== 'highlight' || !isPlainPress(event)) {
    return
  }

  pressPoint = { x: event.clientX, y: event.clientY }
  emit('typePress', typeRef(entry), event)
}

/** What a header reads, the component leading it in a tree of one address. */
function headerText(entry: ParticleTypeEntry): string {
  const name = describeParticleTypeEntry(entry)
  return bare ? `${address.toString()}::particles::${name}` : name
}

/** Whether the pointer moved far enough since the press for the gesture to be a drag rather
than a click. A keyboard activation reports no press at all and is never one. */
function travelled(event: MouseEvent): boolean {
  const from = pressPoint
  pressPoint = null
  if (from == null || event.detail === 0) {
    return false
  }

  return Math.hypot(event.clientX - from.x, event.clientY - from.y) > 4
}
</script>

<template>
  <define-type-list>
    <div>
      <div v-if="shownTypes.length === 0" class="px-2 py-1">
        <c-text variant="description">
          {{ effectiveFilter === '' ? 'No declared particle types.' : 'No matching fields.' }}
        </c-text>
      </div>
      <div v-for="entry in shownTypes" :key="typeRefKey(typeRef(entry))">
        <button
          class="hover:bg-elevated/50 flex w-full select-none items-center gap-1 px-2 py-0.5 text-left"
          :class="[
            (typeHasSelection(entry) || isTypeSelected(entry)) && 'text-primary',
            // Neutral rather than a semantic color, so the highlight never fights the text.
            isTypeSelected(entry) && 'bg-[#80808029]',
          ]"
          data-particle-type
          type="button"
          @click="onTypeClick(entry, $event as MouseEvent)"
          @contextmenu="
            selectionMode === 'highlight' &&
            emit('typeContext', typeRef(entry), $event as MouseEvent)
          "
          @mousedown="(event: MouseEvent) => event.shiftKey && event.preventDefault()"
          @pointerdown="onTypePointerDown(entry, $event as PointerEvent)"
        >
          <c-icon
            class="text-muted shrink-0 transition-transform"
            :class="isTypeOpened(entry) && 'rotate-90'"
            :name="icons.chevronRight"
            size="14"
          />
          <div class="min-w-0">
            <c-text variant="mono-sm">{{ headerText(entry) }}</c-text>
            <c-text v-if="entry.description" variant="description">
              {{ entry.description }}
            </c-text>
          </div>
        </button>
        <div v-if="isTypeOpened(entry)" class="pl-5">
          <div
            v-for="field in entry.fields"
            :key="field.name"
            :class="[
              'group hover:bg-elevated/50 flex min-h-6 items-center',
              'gap-2 rounded-sm px-1 select-none',
              // The pointer cursor marks the toggling row, the highlighting one only selecting
              // the field.
              selectionMode === 'toggle' && 'cursor-pointer',
              // Neutral rather than a semantic color, so the highlight never fights the text.
              selectionMode === 'highlight' && isFieldOn(entry, field.name) && 'bg-[#80808029]',
            ]"
            data-particle-field
            @click="onClick(entry, field, $event as MouseEvent)"
            @contextmenu="onContext(entry, field.name, $event as MouseEvent)"
            @dblclick="onDoubleClick(entry, field)"
            @mousedown="(event: MouseEvent) => event.shiftKey && event.preventDefault()"
            @pointerdown="onPointerDown(entry, field.name, $event as PointerEvent)"
          >
            <c-checkbox
              v-if="selectionMode === 'toggle'"
              :model-value="isFieldOn(entry, field.name)"
              size="xs"
              @click.stop
              @update:model-value="
                (value) => emit('toggle', fieldRef(entry, field.name), Boolean(value))
              "
            />
            <div class="flex min-w-0 grow items-baseline gap-2 whitespace-nowrap">
              <c-text
                :class="isFieldOn(entry, field.name) && 'text-primary'"
                inline
                variant="mono-sm"
              >
                {{ field.name }}:
              </c-text>
              <c-text class="text-muted" inline variant="mono-sm">
                {{ describeFieldType(field.schema as Schema) }}
              </c-text>
              <span
                v-if="describeFieldDescription(field.schema)"
                class="text-muted truncate text-[11px]"
              >
                {{ describeFieldDescription(field.schema) }}
              </span>
            </div>
            <c-tooltip v-if="itemActions" text="More Actions">
              <c-button
                class="opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
                color="neutral"
                :icon="icons.more"
                size="xs"
                square
                variant="ghost"
                @click.stop="onActions($event as MouseEvent)"
                @pointerdown.stop
              />
            </c-tooltip>
          </div>
        </div>
      </div>
    </div>
  </define-type-list>

  <!-- A one-address tree starts at its types since the address level would only repeat the
  page. -->
  <reuse-type-list v-if="bare" />
  <!-- An address declaring nothing has nothing to expand, so it stands as a quiet row. -->
  <div v-else-if="types.length === 0" class="px-2 py-0.5 opacity-55">
    <c-text variant="mono-sm">{{ address.toString() }}</c-text>
  </div>
  <div v-else>
    <button
      class="hover:bg-elevated/50 flex w-full items-center gap-1 px-2 py-0.5 text-left"
      :class="addressHasSelection && 'text-primary'"
      type="button"
      @click="expanded = !expanded"
    >
      <c-icon
        class="text-muted shrink-0 transition-transform"
        :class="expanded && 'rotate-90'"
        :name="icons.chevronRight"
        size="14"
      />
      <c-text variant="mono-sm">{{ address.toString() }}</c-text>
    </button>
    <div v-if="expanded" class="pl-3">
      <reuse-type-list />
    </div>
  </div>

  <c-particle-field-details-dialog v-model="detailsField" />
</template>
