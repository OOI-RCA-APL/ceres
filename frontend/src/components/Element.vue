<template>
  <q-markup-table bordered dense flat separator="cell">
    <thead>
      <q-tr no-hover>
        <q-th>{{ info.name }}</q-th>
      </q-tr>
    </thead>
    <tbody>
      <q-tr no-hover>
        <q-td>
          <div class="justify-center row">
            <gauge-element v-if="info.type === 'gauge'" :info="info" />
            <number-element v-else-if="info.type === 'number'" :info="info" />
          </div>
        </q-td>
      </q-tr>
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
