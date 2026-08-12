<script lang="ts" setup>
import { QMenu } from 'quasar'

import { Address, AddressSelector } from '@/api/address'
import ParticleFieldDetailsDialog, {
  ParticleFieldDetails,
} from '@/components/ParticleFieldDetailsDialog.vue'
import ParticleSeriesSelector from '@/components/ParticleSeriesSelector.vue'
import icons from '@/icons'
import { fieldRefKey, ParticleFieldRef } from '@/particle-series'
import { useParticleTypes } from '@/particle-types'
import { toTitle } from '@/utilities'
import {
  ChartWidget,
  ChartWidgetParticleModel,
  MeterWidget,
  Widget,
  WidgetPlacement,
  createWidget,
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
    | ((widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) => void)
    | null

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
  defineModel<Record<string, boolean> | null>('expandedTypes', { default: null })
)

const types = $(useParticleTypes(() => address.toString()).types)

let selection = $ref<ParticleFieldRef[]>([])

const menu = $ref<QMenu | null>(null)

/** The field the open context menu was raised on. */
let contextRef = $ref<ParticleFieldRef | null>(null)

/** The field whose details dialog is showing, opened from the context menu. */
let detailsField = $ref<ParticleFieldDetails | null>(null)

function showDetails() {
  if (contextRef == null) {
    return
  }

  const field = types
    .find((type) => type.type === contextRef?.type)
    ?.fields.find((field) => field.name === contextRef?.field)
  if (field == null) {
    return
  }

  detailsField = { address: contextRef.address, type: contextRef.type, field }
}

/** One chart plotting every given field, grouped into an entry per particle type. */
function chartWidgetFor(refs: ParticleFieldRef[]): ChartWidget | null {
  const byType = new Map<string, string[]>()
  for (const ref of refs) {
    byType.set(ref.type, [...(byType.get(ref.type) ?? []), ref.field])
  }

  if (byType.size === 0) {
    return null
  }

  const widget = createWidget('chart') as ChartWidget
  widget.particles = [...byType.entries()].map(([type, fields]) =>
    ChartWidgetParticleModel.parse({
      address: new AddressSelector(address.toString()),
      type,
      series: fields.map((field) => ({ field })),
    })
  )

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

  // Named after what is in hand rather than the kind, since what the drop creates is only
  // chosen on release.
  widget.name = refs.length === 1 ? toTitle(refs[0].field) : `${refs.length} Fields`

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

  const widgets = pendingDrop.refs.flatMap((ref) => {
    const widget = chartWidgetFor([ref])
    if (widget == null) {
      return []
    }

    widget.name = toTitle(ref.field)
    return [widget]
  })
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
  <q-list v-if="types.length > 0" bordered class="q-mt-md rounded-borders" dense>
    <q-expansion-item v-model="expanded" dense dense-toggle :label="`Particles (${types.length})`">
      <particle-series-selector
        v-model:expanded-types="expandedTypes"
        v-model:selected="selection"
        :address="address.toString()"
        frameless
        item-actions
        selection-mode="highlight"
        @item-context="
          (event, ref) => {
            contextRef = ref
            menu?.show(event)
          }
        "
        @item-press="onItemPress"
      />
      <q-menu ref="menu" context-menu>
        <q-list bordered dense>
          <q-item v-close-popup clickable dense :disable="contextRef == null" @click="showDetails">
            <q-item-section avatar>
              <q-icon :name="icons.details" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Show Details</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-close-popup
            clickable
            dense
            :disable="selection.length === 0"
            @click="createChart"
          >
            <q-item-section avatar>
              <q-icon :name="icons.chart" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Create Chart</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-close-popup
            clickable
            dense
            :disable="selection.length === 0"
            @click="createMeters"
          >
            <q-item-section avatar>
              <q-icon :name="icons.meter" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Create Meter</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-menu>
      <particle-field-details-dialog v-model="detailsField" />
      <q-dialog
        :model-value="pendingDrop != null"
        @update:model-value="(value) => !value && (pendingDrop = null)"
      >
        <q-card v-if="pendingDrop != null" bordered flat>
          <q-list dense :style="{ minWidth: '220px' }">
            <q-item v-close-popup clickable dense @click="dropChart">
              <q-item-section avatar>
                <q-icon :name="icons.chart" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Create Chart</q-item-label>
              </q-item-section>
            </q-item>
            <q-item
              v-if="pendingDrop.refs.length > 1"
              v-close-popup
              clickable
              dense
              @click="dropSeparateCharts"
            >
              <q-item-section avatar>
                <q-icon :name="icons.chart" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Create Separate Charts</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-close-popup clickable dense @click="dropMeters">
              <q-item-section avatar>
                <q-icon :name="icons.meter" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  Create {{ pendingDrop.refs.length > 1 ? 'Meters' : 'Meter' }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </q-dialog>
    </q-expansion-item>
  </q-list>
</template>
