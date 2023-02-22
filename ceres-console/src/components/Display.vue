<template>
  <q-card bordered class="column full-height self-root" flat>
    <q-markup-table dense flat separator="cell">
      <thead class="self-header">
        <q-tr no-hover>
          <q-th>{{ display.title }}</q-th>
        </q-tr>
      </thead>
    </q-markup-table>
    <div class="col-grow items-center justify-center q-pa-xs row">
      <template v-if="info">
        <value-display v-if="info.kind === 'value'" :info="info" />
        <state-display v-else-if="info.kind === 'state'" :info="info" />
        <gauge-display v-else-if="info.kind === 'gauge'" :info="info" />
        <chart-display v-else-if="info.kind === 'chart'" :info="info" />
      </template>
      <template v-else><q-spinner /></template>
    </div>
  </q-card>
</template>

<script lang="ts" setup>
import { LayoutDisplay } from '@/api/models'
import { useDisplayStream } from '@/api/queries'
import ChartDisplay from '@/components/displays/ChartDisplay.vue'
import GaugeDisplay from '@/components/displays/GaugeDisplay.vue'
import StateDisplay from '@/components/displays/StateDisplay.vue'
import ValueDisplay from '@/components/displays/ValueDisplay.vue'
import { DisplayInfo } from '@/display'
import { QMarkupTable, QTh, QTr } from 'quasar'

const { unitName, componentName, display } = defineProps<{
  unitName: string
  componentName: string
  display: LayoutDisplay
}>()

let info: DisplayInfo | null = $ref(null)

useDisplayStream(unitName, componentName, display.procedure, (current) => {
  info = current
})
</script>

<style lang="scss" scoped>
.body--dark .self-root {
  background-color: #131313;
}

.self-header {
  background-color: $grey-1;
}

.body--dark .self-header {
  background-color: #1d1d1d;
}
</style>
