<script lang="ts" setup>
import { watch } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { seriesForGroup } from '@/particle-series'
import { describeFieldDescription, describeFieldType, useParticleTypes } from '@/particle-types'
import { Schema } from '@/schema-form'
import { ChartWidgetParticle, SelectMode } from '@/workspace'

const {
  address,
  particles = [],
  selectionMode = 'toggle',
  selectedKeys = new Set<string>(),
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

let expanded = $ref(defaultOpened || bare)

// Fetched only once expanded so an address nobody opens costs no request.
const types = $(useParticleTypes(() => (expanded ? address.toString() : null)).types)

watch(
  () => types,
  () => emit('loaded', types)
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

function onClick(type: string, field: string, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('select', type, field, modeOf(event))
  }
}

function onContext(type: string, field: string, event: MouseEvent) {
  if (selectionMode === 'highlight') {
    emit('context', type, field, event)
  }
}
</script>

<template>
  <!-- Bare hides the header and drops the inset so a one-address tree starts at its types. -->
  <q-expansion-item
    v-model="expanded"
    :content-inset-level="bare ? 0 : 0.4"
    dense
    dense-toggle
    :header-class="bare ? 'hidden' : undefined"
  >
    <template #header>
      <q-item-section>
        <q-item-label class="monospace-sm">{{ address.toString() }}</q-item-label>
      </q-item-section>
    </template>
    <q-list dense>
      <q-item v-if="types.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">No declared particle types.</q-item-label>
        </q-item-section>
      </q-item>
      <q-expansion-item
        v-for="type in types"
        :key="type.type"
        :content-inset-level="0.4"
        default-opened
        dense
        dense-toggle
      >
        <template #header>
          <q-item-section>
            <q-item-label class="monospace-sm">{{ type.type }}</q-item-label>
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
            :clickable="selectionMode === 'highlight'"
            :tag="selectionMode === 'toggle' ? 'label' : 'div'"
            @click="onClick(type.type, field.name, $event as MouseEvent)"
            @contextmenu="onContext(type.type, field.name, $event as MouseEvent)"
          >
            <q-item-section v-if="selectionMode === 'toggle'" side>
              <q-checkbox
                dense
                :model-value="isFieldOn(type.type, field.name)"
                @update:model-value="
                  (value) => emit('toggle', type.type, field.name, Boolean(value))
                "
              />
            </q-item-section>
            <q-item-section>
              <q-item-label class="items-baseline no-wrap q-gutter-x-sm row">
                <span class="monospace-sm">{{ field.name }}</span>
                <span class="monospace-sm text-grey-6">
                  {{ describeFieldType(field.schema as Schema) }}
                </span>
                <span v-if="describeFieldDescription(field.schema)" class="ellipsis text-grey-6">
                  {{ describeFieldDescription(field.schema) }}
                </span>
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>
    </q-list>
  </q-expansion-item>
</template>

<style module>
/* Neutral so the highlight reads the same over both themes and never fights the text color. */
.selected {
  background: #80808029;
}
</style>
