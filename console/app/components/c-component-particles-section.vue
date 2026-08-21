<script lang="ts" setup>
import type { ContextMenuItem } from '@nuxt/ui'

import { type Address, AddressSelector } from '@/api/address'
import type { ParticleFieldDetails } from '@/components/c-particle-field-details-dialog.vue'
import icons from '@/icons'
import { fieldRefKey, type ParticleFieldRef, toggleParticleField } from '@/particle-series'
import { useParticleTypes } from '@/particle-types'
import { toTitle } from '@/utilities'
import {
  type ChartWidget,
  type ChartWidgetParticle,
  createWidget,
  type MeterWidget,
  type Widget,
  type WidgetPlacement,
} from '@/workspace'

const {
  address,
  insertDrag = null,
  insertAt = null,
} = defineProps<{
  address: Address

  /** Starts a workspace insertion drag on a pressed field, handed down by a page hosting a
  workspace. Absent, field rows offer no drag. */
  insertDrag?:
    ((widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) => void) | null

  /** Inserts widgets where an insertion drag landed. */
  insertAt?: ((widgets: Widget[], placement: WidgetPlacement) => void) | null
}>()

const emit = defineEmits<{
  /** Widgets built from the selected fields, for the caller to land on the component's strip. */
  create: [widgets: Widget[]]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

/** Remembered type expansion, persisted by the hosting page. */
let expandedTypes = $(
  defineModel<Record<string, boolean> | null>('expandedTypes', { default: null }),
)

const types = $(useParticleTypes(() => address.toString()).types)

let selection = $ref<ParticleFieldRef[]>([])

/** The field the open context menu was raised on. */
let contextRef = $ref<ParticleFieldRef | null>(null)

/** The field whose details dialog is showing, opened from the context menu. */
let detailsField = $ref<ParticleFieldDetails | null>(null)

const menuItems = $computed<ContextMenuItem[][]>(() => [
  [
    {
      label: 'Show Details',
      icon: icons.details,
      disabled: contextRef == null,
      onSelect: showDetails,
    },
    {
      label: 'Create Chart',
      icon: icons.chart,
      disabled: selection.length === 0,
      onSelect: createChart,
    },
    {
      label: 'Create Meter',
      icon: icons.meter,
      disabled: selection.length === 0,
      onSelect: createMeters,
    },
  ],
])

// Every item here acts on a field, so a right click landing elsewhere in the tree is defaulted
// and the menu's trigger leaves it alone.
function onTreeContext(event: MouseEvent) {
  if ((event.target as HTMLElement).closest('[data-particle-field]') == null) {
    event.preventDefault()
  }
}

function showDetails() {
  if (contextRef == null) {
    return
  }

  const field = types
    .find((type) => type.type === contextRef?.type)
    ?.fields.find((current) => current.name === contextRef?.field)
  if (field == null) {
    return
  }

  detailsField = { address: contextRef.address, type: contextRef.type, field }
}

/** One chart plotting every given field, grouped the same way the selectors' toggles group.

A chart of one field is named after it, since that name is the whole of what it plots. Several
fields keep the default, no one of them standing for the rest.
*/
function chartWidgetFor(refs: ParticleFieldRef[]): ChartWidget | null {
  if (refs.length === 0) {
    return null
  }

  const widget = createWidget('chart') as ChartWidget
  widget.particles = refs.reduce<ChartWidgetParticle[]>(
    (particles, ref) =>
      toggleParticleField(particles, address.toString(), ref.type, ref.field, true),
    [],
  )
  if (refs.length === 1) {
    widget.name = toTitle(refs[0]!.field)
  }

  return widget
}

/** One meter per given field, each named after the field it shows. */
function meterWidgetsFor(refs: ParticleFieldRef[]): MeterWidget[] {
  return refs.map((ref) => {
    const widget = createWidget('meter') as MeterWidget
    widget.name = toTitle(ref.field)
    widget.particleAddress = new AddressSelector(address.toString())
    widget.particleType = ref.type
    widget.particleField = ref.field
    return widget
  })
}

function createChart() {
  const widget = chartWidgetFor(selection)
  if (widget != null) {
    emit('create', [widget])
  }
}

function createMeters() {
  if (selection.length > 0) {
    emit('create', meterWidgetsFor(selection))
  }
}

/** A drop waiting on the chart-or-values prompt, with the fields that were dragged. */
let pendingDrop = $ref<{ placement: WidgetPlacement; refs: ParticleFieldRef[] } | null>(null)

// The drag carries the pressed field, or the whole selection when the press landed inside it,
// the same rule the context menu applies. A chart widget stands in for the preview since the
// choice of what to create is only asked on release.
function onItemPress(event: PointerEvent, ref: ParticleFieldRef) {
  if (insertDrag == null || insertAt == null) {
    return
  }

  const key = fieldRefKey(ref)
  const refs = selection.some((current) => fieldRefKey(current) === key) ? [...selection] : [ref]
  const widget = chartWidgetFor(refs)
  if (widget == null) {
    return
  }

  insertDrag([widget], (placement) => {
    if (placement != null) {
      pendingDrop = { placement, refs }
    }
  })
}

function dropChart() {
  if (pendingDrop == null) {
    return
  }

  const widget = chartWidgetFor(pendingDrop.refs)
  if (widget != null) {
    insertAt?.([widget], pendingDrop.placement)
  }

  pendingDrop = null
}

/** One chart per dragged field, each named after the field it plots. */
function dropSeparateCharts() {
  if (pendingDrop == null) {
    return
  }

  const widgets = pendingDrop.refs.flatMap((ref) => chartWidgetFor([ref]) ?? [])
  insertAt?.(widgets, pendingDrop.placement)
  pendingDrop = null
}

function dropMeters() {
  if (pendingDrop == null) {
    return
  }

  insertAt?.(meterWidgetsFor(pendingDrop.refs), pendingDrop.placement)
  pendingDrop = null
}
</script>

<template>
  <div v-if="types.length > 0" class="border-default rounded-md border">
    <c-detail-section v-model:expanded="expanded" :title="`Particles (${types.length})`">
      <c-context-menu :items="menuItems">
        <c-particle-series-selector
          v-model:expanded-types="expandedTypes"
          v-model:selected="selection"
          :address="address.toString()"
          frameless
          item-actions
          selection-mode="highlight"
          @contextmenu="onTreeContext"
          @item-context="(event, ref) => (contextRef = ref)"
          @item-press="onItemPress"
        />
      </c-context-menu>
    </c-detail-section>
    <c-particle-field-details-dialog v-model="detailsField" />
    <!-- What a dragged field becomes is only asked once it lands, since the same drag can build
    either a plot of the fields or a value readout of each. -->
    <c-modal
      :open="pendingDrop != null"
      title="Add Widgets"
      @update:open="(value: boolean) => !value && (pendingDrop = null)"
    >
      <template #body>
        <div v-if="pendingDrop != null" class="flex min-w-56 flex-col gap-1">
          <c-button
            block
            color="neutral"
            :icon="icons.chart"
            label="Create Chart"
            :ui="{ label: 'grow text-left' }"
            variant="ghost"
            @click="dropChart"
          />
          <c-button
            v-if="pendingDrop.refs.length > 1"
            block
            color="neutral"
            :icon="icons.chart"
            label="Create Separate Charts"
            :ui="{ label: 'grow text-left' }"
            variant="ghost"
            @click="dropSeparateCharts"
          />
          <c-button
            block
            color="neutral"
            :icon="icons.meter"
            :label="`Create ${pendingDrop.refs.length > 1 ? 'Meters' : 'Meter'}`"
            :ui="{ label: 'grow text-left' }"
            variant="ghost"
            @click="dropMeters"
          />
        </div>
      </template>
    </c-modal>
  </div>
</template>
