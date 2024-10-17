<script lang="ts" setup>
import { Particle } from '@/api/particles'
import RecordViewRecord from '@/components/RecordViewRecord.vue'
import { highlight } from '@/utilities'

const { particle } = defineProps<{
  particle: Particle
}>()

const renderedData = $computed(() => highlight(JSON.stringify(particle.data), 'json'))
// const renderedData = $computed(() => JSON.stringify(particle.data))
</script>

<template>
  <record-view-record :record="particle">
    <q-td>
      <span class="monospace-xs">
        {{ particle.type }}
      </span>
    </q-td>
    <q-td>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div :class="$style.data" v-html="renderedData" />
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.data {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}
</style>
