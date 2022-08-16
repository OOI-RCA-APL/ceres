<template>
  <q-markup-table flat bordered dense separator="cell">
    <thead>
      <tr>
        <th>{{ info.name }}</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>
          <gauge-element v-if="info.type === 'gauge'" :info="info" />
          <number-element v-else-if="info.type === 'number'" :info="info" />
        </td>
      </tr>
    </tbody>
  </q-markup-table>
</template>

<script lang="ts" setup>
import GaugeElement from '@/components/elements/GaugeElement.vue'
import NumberElement from '@/components/elements/NumberElement.vue'
import type { ElementInfo } from '@/element'

defineProps<{
  info: ElementInfo
}>()
</script>
