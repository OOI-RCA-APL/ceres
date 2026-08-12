<script lang="ts" setup>
import { QMenu } from 'quasar'

import { Address, AddressSelector } from '@/api/address'
import ParticleSeriesSelector from '@/components/ParticleSeriesSelector.vue'
import icons from '@/icons'
import { ParticleFieldRef } from '@/particle-series'
import { useParticleTypes } from '@/particle-types'
import {
  ChartWidget,
  ChartWidgetParticleModel,
  ValueWidget,
  Widget,
  createWidget,
} from '@/workspace'

const { address } = defineProps<{
  address: Address
}>()

const emit = defineEmits<{
  /** Widgets built from the selected fields, for the caller to land on the component's strip. */
  create: [widgets: Widget[]]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

const types = $(useParticleTypes(() => address.toString()).types)

let selection = $ref<ParticleFieldRef[]>([])

const menu = $ref<QMenu | null>(null)

/** One chart plotting every selected field, grouped into an entry per particle type. */
function createChart() {
  const byType = new Map<string, string[]>()
  for (const ref of selection) {
    byType.set(ref.type, [...(byType.get(ref.type) ?? []), ref.field])
  }

  if (byType.size === 0) {
    return
  }

  const widget = createWidget('chart') as ChartWidget
  widget.particles = [...byType.entries()].map(([type, fields]) =>
    ChartWidgetParticleModel.parse({
      address: new AddressSelector(address.toString()),
      type,
      series: fields.map((field) => ({ field })),
    })
  )
  emit('create', [widget])
}

/** One value view per selected field, each named after the field it shows. */
function createValueViews() {
  if (selection.length === 0) {
    return
  }

  emit(
    'create',
    selection.map((ref) => {
      const widget = createWidget('value') as ValueWidget
      widget.name = ref.field
      widget.particleAddress = new AddressSelector(address.toString())
      widget.particleType = ref.type
      widget.particleField = ref.field
      return widget
    })
  )
}
</script>

<template>
  <q-list v-if="types.length > 0" bordered class="q-mt-md rounded-borders" dense>
    <q-expansion-item v-model="expanded" dense dense-toggle :label="`Particles (${types.length})`">
      <div class="items-center justify-end q-px-sm q-py-xs row">
        <q-btn
          dense
          :disable="selection.length === 0"
          flat
          :icon="icons.more"
          round
          size="7px"
          @click="menu?.show($event)"
        >
          <q-tooltip>More Actions</q-tooltip>
        </q-btn>
      </div>
      <div @contextmenu.prevent="menu?.show($event)">
        <particle-series-selector
          v-model:selected="selection"
          :address="address.toString()"
          selection-mode="highlight"
          @item-context="(event) => menu?.show(event)"
        />
      </div>
      <q-menu ref="menu" context-menu>
        <q-list bordered dense>
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
            @click="createValueViews"
          >
            <q-item-section avatar>
              <q-icon :name="icons.value" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Create Value View</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </q-expansion-item>
  </q-list>
</template>
