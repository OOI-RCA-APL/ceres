<script lang="ts" setup>
import { createReusableTemplate } from '@vueuse/core'
import { watch } from 'vue'

import { Address } from '@/api/address'
import { ParticleFieldInfo, ParticleTypeInfo } from '@/api/components'
import icons from '@/icons'
import { seriesForGroup } from '@/particle-series'
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
} = defineProps<{
  address: Address

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
}>()

const emit = defineEmits<{
  /** A field's toggle changed for one of this address's declared particle types. */
  toggle: [type: string, field: string, value: boolean]

  /** A highlight-mode click, with the select mode the held modifiers ask for. */
  select: [type: string, field: string, mode: SelectMode]

  /** A right click on a field row, before the hosting menu opens on the event. */
  context: [type: string, field: string, event: MouseEvent]

  /** This address's declared types resolved, for the host's selection ordering. */
  loaded: [types: ParticleTypeInfo[]]
}>()

// The type list renders inside the address expansion item, or on its own in bare mode.
const [DefineTypeList, ReuseTypeList] = createReusableTemplate()

let expanded = $ref(defaultOpened || bare)

// Fetched only once expanded so an address nobody opens costs no request.
const types = $(useParticleTypes(() => (expanded ? address.toString() : null)).types)

// Immediate because the query cache can hold the types before this mounts, in which case they
// never change and a change-only watch would leave the host's selection ordering empty.
watch(
  () => types,
  () => emit('loaded', types),
  { immediate: true }
)

function selectedFields(type: string): string[] {
  return seriesForGroup(particles, address.toString(), type)
    .map((series) => series.field)
    .filter((field): field is string => field != null)
}

function isFieldOn(type: string, field: string): boolean {
  if (selectionMode === 'highlight') {
    return selectedKeys.has(`${address.toString()}|${type}|${field}`)
  }

  return selectedFields(type).includes(field)
}

/** The select mode a click's modifiers ask for, matching the workspace's own vocabulary. */
function modeOf(event: MouseEvent): SelectMode {
  if (event.shiftKey) {
    return 'extend'
  }

  return event.metaKey || event.ctrlKey ? 'toggle' : 'replace'
}

/** The field whose details dialog is showing, with the type it belongs to. */
let detailsField = $ref<{ type: string; field: ParticleFieldInfo } | null>(null)

// A highlight click is a selection, so the details dialog is reserved for toggle mode, where
// the checkbox already carries the choice.
function onClick(type: string, field: ParticleFieldInfo, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('select', type, field.name, modeOf(event))
  } else {
    detailsField = { type, field }
  }
}

function onContext(type: string, field: string, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    event.preventDefault()
    emit('context', type, field, event)
  }
}
</script>

<template>
  <define-type-list>
    <q-list dense>
      <q-item v-if="types.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">No declared particle types.</q-item-label>
        </q-item-section>
      </q-item>
      <q-expansion-item
        v-for="type in types"
        :key="type.type"
        :content-inset-level="0.2"
        default-opened
        dense
        dense-toggle
        :header-class="$style.groupHeader"
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
            @mousedown="(event: MouseEvent) => event.shiftKey && event.preventDefault()"
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
                <span class="monospace-sm">{{ field.name }}:</span>
                <span class="monospace-sm text-grey-6">
                  {{ describeFieldType(field.schema as Schema) }}
                </span>
                <span
                  v-if="describeFieldDescription(field.schema)"
                  :class="$style.fieldDescription"
                  class="ellipsis text-grey-6"
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
  <q-expansion-item
    v-else
    v-model="expanded"
    :content-inset-level="0.2"
    dense
    dense-toggle
    :header-class="$style.groupHeader"
  >
    <template #header>
      <q-item-section>
        <q-item-label class="monospace-sm">{{ address.toString() }}</q-item-label>
      </q-item-section>
    </template>
    <reuse-type-list />
  </q-expansion-item>

  <q-dialog
    :model-value="detailsField != null"
    @update:model-value="(value) => !value && (detailsField = null)"
  >
    <q-card v-if="detailsField != null" bordered flat :style="{ minWidth: '320px' }">
      <div class="column q-gutter-y-sm q-pa-md">
        <div class="items-baseline q-gutter-x-sm row">
          <span class="monospace-sm text-weight-medium">{{ detailsField.field.name }}:</span>
          <span class="monospace-sm text-grey-6">
            {{ describeFieldType(detailsField.field.schema as Schema) }}
          </span>
        </div>
        <div class="monospace-sm text-grey-6">
          {{ address.toString() }}::particles::{{ detailsField.type }}
        </div>
        <div v-if="describeFieldDescription(detailsField.field.schema)">
          {{ describeFieldDescription(detailsField.field.schema) }}
        </div>
        <div v-else class="text-grey-6">No description.</div>
      </div>
    </q-card>
  </q-dialog>
</template>

<style module>
/* Neutral so the highlight reads the same over both themes and never fights the text color. */
.selected {
  background: #80808029;
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
