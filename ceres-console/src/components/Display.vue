<template>
  <q-markup-table bordered dense flat separator="cell">
    <thead>
      <q-tr no-hover>
        <q-th>{{ capitalCase(displayName) }}</q-th>
      </q-tr>
    </thead>
    <tbody :style="$q.dark.isActive ? 'background-color: #131313' : ''">
      <q-tr no-hover>
        <q-td>
          <div :key="JSON.stringify(info)" class="justify-center row">
            <template v-if="info">
              <guage-display v-if="info.kind === 'gauge'" :info="info" />
              <number-display v-else-if="info.kind === 'number'" :info="info" />
              <indicator-display v-else-if="info.kind === 'indicator'" :info="info" />
              <state-display v-else-if="info.kind === 'state'" :info="info" />
            </template>
            <template v-else> Loading... </template>
          </div>
        </q-td>
      </q-tr>
    </tbody>
  </q-markup-table>
</template>

<script lang="ts" setup>
import { useDisplayStream } from '@/api/queries'
import { DisplayInfo } from '@/display'
import { capitalCase } from 'change-case'
import GuageDisplay from './displays/GuageDisplay.vue'
import IndicatorDisplay from './displays/IndicatorDisplay.vue'
import NumberDisplay from './displays/NumberDisplay.vue'
import StateDisplay from './displays/StateDisplay.vue'

const { unitName, componentName, displayName } = defineProps<{
  unitName: string
  componentName: string
  displayName: string
}>()

let info: DisplayInfo | null = $ref(null)

useDisplayStream(unitName, componentName, displayName, (current) => {
  info = current
})
</script>
