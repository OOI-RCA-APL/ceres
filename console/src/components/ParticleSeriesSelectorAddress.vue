<script lang="ts" setup>
import { createReusableTemplate } from '@vueuse/core'
import { nextTick, watch } from 'vue'

import { Address } from '@/api/address'
import { ParticleFieldInfo, ParticleTypeInfo } from '@/api/components'
import ParticleFieldDetailsDialog, {
  ParticleFieldDetails,
} from '@/components/ParticleFieldDetailsDialog.vue'
import icons from '@/icons'
import { fieldRefKey } from '@/particle-series'
import { describeFieldDescription, describeFieldType, useParticleTypes } from '@/particle-types'
import { Schema } from '@/schema-form'
import { ChartWidgetParticle, SelectMode } from '@/workspace'

const {
  address,
  particles = [],
  selectionMode = 'toggle',
  selectedKeys = new Set<string>(),
  itemActions = false,
  bare = false,
  defaultOpened = false,
  collapseUnselected = false,
  filter = '',
  shownTypes,
} = defineProps<{
  address: Address

  /** The rows to render, the address's declared types as the host's search narrowed them. */
  shownTypes: ParticleTypeInfo[]

  /** The chart model's particle entries, read in toggle mode to mark which fields are on. */
  particles?: ChartWidgetParticle[]

  /** Whether fields toggle with checkboxes or select as highlighted rows. */
  selectionMode?: 'toggle' | 'highlight'

  /** The selection in highlight mode, as `fieldRefKey` keys spanning the whole tree. */
  selectedKeys?: Set<string>

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

/** Remembered type expansion by `address|type` key, for hosts that persist the tree between
visits. Types without an entry fall back to the default. */
let expandedTypes = $(
  defineModel<Record<string, boolean> | null>('expandedTypes', { default: null })
)

function isTypeOpened(type: ParticleTypeInfo): boolean {
  const remembered = expandedTypes?.[`${address.toString()}|${type.type}`]
  if (remembered != null) {
    return remembered
  }

  return !collapseUnselected || typeHasSelection(type)
}

function rememberTypeExpansion(type: string, value: boolean) {
  if (expandedTypes == null || filterSettling || effectiveFilter !== '') {
    return
  }

  expandedTypes = { ...expandedTypes, [`${address.toString()}|${type}`]: value }
}

const emit = defineEmits<{
  /** A field's toggle changed for one of this address's declared particle types. */
  toggle: [type: string, field: string, value: boolean]

  /** A highlight-mode click, with the select mode the held modifiers ask for. */
  select: [type: string, field: string, mode: SelectMode]

  /** A right click on a field row, before the hosting menu opens on the event. */
  context: [type: string, field: string, event: MouseEvent]

  /** A plain press on a field row in highlight mode, which a host may turn into a drag. */
  press: [type: string, field: string, event: PointerEvent]
}>()

// The type list renders inside the address expansion item, or on its own in bare mode.
const [DefineTypeList, ReuseTypeList] = createReusableTemplate()

let expanded = $ref(defaultOpened || bare)

const types = $(useParticleTypes(() => address.toString()).types)

// The address's own name matching is as good as every type matching, so the filter stops
// narrowing below it.
const effectiveFilter = $computed(() =>
  address.toString().toLowerCase().includes(filter) ? '' : filter
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
  }
)

// Items torn down as the filter changes fire hide events of their own, which must not be
// mistaken for the user collapsing anything, so remembering pauses across the swap.
let filterSettling = false

watch(
  () => effectiveFilter,
  async () => {
    filterSettling = true
    await nextTick()
    filterSettling = false
  }
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
        keys.add(`${particle.type}|${series.field}`)
      }
    }
  }

  return keys
})

function isFieldOn(type: string, field: string): boolean {
  if (selectionMode === 'highlight') {
    return selectedKeys.has(fieldRefKey({ address: address.toString(), type, field }))
  }

  return onFieldKeys.has(`${type}|${field}`)
}

function typeHasSelection(type: ParticleTypeInfo): boolean {
  return type.fields.some((field) => isFieldOn(type.type, field.name))
}

// Read against every declared type rather than the filtered view so a selection hidden by a
// search still marks its containers.
const addressHasSelection = $computed(() => types.some(typeHasSelection))

/** The select mode a click's modifiers ask for, matching the workspace's own vocabulary. */
function modeOf(event: MouseEvent): SelectMode {
  if (event.shiftKey) {
    return 'extend'
  }

  return event.metaKey || event.ctrlKey ? 'toggle' : 'replace'
}

/** The field whose details dialog is showing. */
let detailsField = $ref<ParticleFieldDetails | null>(null)

// A highlight click is a selection, so there the details dialog moves to double click. In
// toggle mode the checkbox already carries the choice and a single click opens it.
function onClick(type: string, field: ParticleFieldInfo, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('select', type, field.name, modeOf(event))
  } else {
    detailsField = { address: address.toString(), type, field }
  }
}

function onDoubleClick(type: string, field: ParticleFieldInfo) {
  if (selectionMode === 'highlight') {
    detailsField = { address: address.toString(), type, field }
  }
}

function onContext(type: string, field: string, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    event.preventDefault()
    emit('context', type, field, event)
  }
}

// Only a plain press is offered as a drag. A modified press is a selection gesture, and the
// click that follows an untravelled press still selects as it always did.
function onPointerDown(type: string, field: string, event: PointerEvent) {
  if (selectionMode !== 'highlight' || event.button !== 0) {
    return
  }
  if (event.shiftKey || event.metaKey || event.ctrlKey) {
    return
  }

  emit('press', type, field, event)
}
</script>

<template>
  <define-type-list>
    <q-list dense>
      <q-item v-if="shownTypes.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">
            {{ effectiveFilter === '' ? 'No declared particle types.' : 'No matching fields.' }}
          </q-item-label>
        </q-item-section>
      </q-item>
      <!-- Keyed on whether a search is narrowing so entering one remounts the items opened,
      whatever their remembered state, and leaving it restores that state. -->
      <q-expansion-item
        v-for="type in shownTypes"
        :key="`${type.type}|${effectiveFilter !== ''}`"
        :content-inset-level="0.2"
        :default-opened="effectiveFilter !== '' || isTypeOpened(type)"
        dense
        dense-toggle
        :header-class="[$style.groupHeader, typeHasSelection(type) && $style.containsSelection]"
        @hide="rememberTypeExpansion(type.type, false)"
        @show="rememberTypeExpansion(type.type, true)"
      >
        <template #header>
          <q-item-section>
            <!-- Bare carries the whole path since no address level stands above the types. -->
            <q-item-label class="monospace-sm">
              {{ bare ? `${address.toString()}::particles::${type.type}` : type.type }}
            </q-item-label>
            <q-item-label v-if="type.description" caption>{{ type.description }}</q-item-label>
          </q-item-section>
        </template>
        <q-list dense>
          <q-item
            v-for="field in type.fields"
            :key="field.name"
            v-ripple
            :active="selectionMode === 'highlight' && isFieldOn(type.type, field.name)"
            :active-class="$style.selected"
            :class="$style.fieldRow"
            clickable
            @click="onClick(type.type, field, $event as MouseEvent)"
            @contextmenu="onContext(type.type, field.name, $event as MouseEvent)"
            @dblclick="onDoubleClick(type.type, field)"
            @mousedown="(event: MouseEvent) => event.shiftKey && event.preventDefault()"
            @pointerdown="onPointerDown(type.type, field.name, $event as PointerEvent)"
          >
            <q-item-section v-if="selectionMode === 'toggle'" side @click.stop>
              <q-checkbox
                dense
                :model-value="isFieldOn(type.type, field.name)"
                size="xs"
                @update:model-value="
                  (value) => emit('toggle', type.type, field.name, Boolean(value))
                "
              />
            </q-item-section>
            <q-item-section>
              <q-item-label class="items-baseline no-wrap q-gutter-x-sm row">
                <span
                  class="monospace-sm"
                  :class="isFieldOn(type.type, field.name) && $style.selectedName"
                  >{{ field.name }}:</span
                >
                <span class="monospace-sm text-grey-6">
                  {{ describeFieldType(field.schema as Schema) }}
                </span>
                <span
                  v-if="describeFieldDescription(field.schema)"
                  class="ellipsis text-grey-6"
                  :class="$style.fieldDescription"
                >
                  {{ describeFieldDescription(field.schema) }}
                </span>
              </q-item-label>
            </q-item-section>
            <q-item-section v-if="itemActions" :class="$style.rowActions" side>
              <q-btn
                dense
                flat
                :icon="icons.more"
                round
                size="7px"
                @click.stop="onContext(type.type, field.name, $event as MouseEvent)"
              >
                <q-tooltip>More Actions</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>
    </q-list>
  </define-type-list>

  <!-- A one-address tree starts at its types since the address level would only repeat the
  page. -->
  <reuse-type-list v-if="bare" />
  <!-- An address declaring nothing has nothing to expand, so it stands as a quiet row. -->
  <q-item v-else-if="types.length === 0" :class="[$style.groupHeader, $style.emptyAddress]" dense>
    <q-item-section>
      <q-item-label class="monospace-sm">{{ address.toString() }}</q-item-label>
    </q-item-section>
  </q-item>
  <q-expansion-item
    v-else
    v-model="expanded"
    :content-inset-level="0.2"
    dense
    dense-toggle
    :header-class="[$style.groupHeader, addressHasSelection && $style.containsSelection]"
  >
    <template #header>
      <q-item-section>
        <q-item-label class="monospace-sm">{{ address.toString() }}</q-item-label>
      </q-item-section>
    </template>
    <reuse-type-list />
  </q-expansion-item>

  <particle-field-details-dialog v-model="detailsField" />
</template>

<style lang="scss" module>
/* Neutral so the highlight reads the same over both themes and never fights the text color. */
.selected {
  background: #80808029;
}

// Primary on the text, saying something inside is selected without filling the row.
:global(.q-item).containsSelection {
  color: $primary;
}

.selectedName {
  color: $primary;
}

/* Qualified to outrank the dense item's own min-height. Text selection is off so a shift
click reads as extending the field selection rather than sweeping text. */
:global(.q-item).fieldRow {
  min-height: 24px;
  padding-top: 0;
  padding-bottom: 0;
  user-select: none;
}

:global(.q-item).groupHeader {
  padding-left: 8px;
}

/* Quiet since there is nothing to pick under it, kept on the list so the tree still says the
component exists. */
.emptyAddress {
  opacity: 0.55;
}

/* Sized to sit beside the type text rather than standing out over it. */
.fieldDescription {
  font-size: 11px;
}

/* Offered on the row rather than standing on every one, with focus keeping it reachable by
keyboard. */
.rowActions {
  opacity: 0;
}

.fieldRow:hover .rowActions,
.fieldRow:focus-within .rowActions {
  opacity: 1;
}
</style>
