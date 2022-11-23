<template>
  <q-markup-table bordered dense flat separator="cell">
    <thead>
      <q-tr no-hover>
        <q-th>{{ info.name }}</q-th>
      </q-tr>
    </thead>
    <tbody :style="$q.dark.isActive ? 'background-color: #131313' : ''">
      <q-tr no-hover>
        <q-td>
          <div class="justify-center row">
            <gauge-element v-if="info.type === 'gauge'" :info="info" />
            <half-gauge-element v-if="info.type === 'halfgauge'" :info="info" />
            <number-element v-else-if="info.type === 'number'" :info="info" />
            <indicator-element v-else-if="info.type === 'indicator'" :info="info" />
            <state-element v-else-if="info.type === 'state'" :info="info" />
          </div>
        </q-td>
      </q-tr>
    </tbody>
  </q-markup-table>
</template>

<script lang="ts" setup>
import GaugeElement from '@/components/elements/GaugeElement.vue'
import NumberElement from '@/components/elements/NumberElement.vue'
import StateElement from './elements/StateElement.vue'
import type { ElementInfo } from '@/element'
import IndicatorElement from './elements/IndicatorElement.vue'
import HalfGaugeElement from './elements/HalfGaugeElement.vue'

defineProps<{
  info: ElementInfo
}>()
</script>
