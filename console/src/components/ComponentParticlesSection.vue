<script lang="ts" setup>
import { QMenu } from 'quasar'

import { Address } from '@/api/address'
import ParticleSeriesSelector from '@/components/ParticleSeriesSelector.vue'
import icons from '@/icons'
import { useParticleTypes } from '@/particle-types'
import {
  ChartWidget,
  ChartWidgetParticle,
  ChartWidgetParticleModel,
  createWidget,
} from '@/workspace'

const { address } = defineProps<{
  address: Address
}>()

const emit = defineEmits<{
  /** A chart widget built from the currently toggled particle series, for the caller to land
  on the component's strip. */
  createChart: [widget: ChartWidget]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

const types = $(useParticleTypes(() => address.toString()).types)

let selection = $ref<ChartWidgetParticle[]>([])

const menu = $ref<QMenu | null>(null)

function createChart() {
  if (selection.length === 0) {
    return
  }

  const widget = createWidget('chart') as ChartWidget
  // Cloned rather than assigned so the tree's own selection state never ends up aliased into
  // the widget once it lands in a workspace's layout.
  widget.particles = selection.map((particle) => ChartWidgetParticleModel.parse(particle))
  emit('createChart', widget)
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
        <particle-series-selector v-model="selection" :address="address.toString()" />
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
        </q-list>
      </q-menu>
    </q-expansion-item>
  </q-list>
</template>
