<script lang="ts" setup>
import { LayoutDisplay } from '@/api/models'
import ChartDisplay from '@/components/displays/ChartDisplay.vue'
import GaugeDisplay from '@/components/displays/GaugeDisplay.vue'
import StateDisplay from '@/components/displays/StateDisplay.vue'
import ValueDisplay from '@/components/displays/ValueDisplay.vue'
import { DisplayInfo } from '@/display'

const {
  display,
  info,
  titleClickable = false,
} = defineProps<{
  display: LayoutDisplay
  info: DisplayInfo | null
  titleClickable?: boolean
}>()

const emit = defineEmits<{
  (emit: 'title-click'): void
}>()
</script>

<template>
  <div class="column self-display-content-root">
    <q-markup-table dense flat separator="cell">
      <thead class="self-header">
        <q-tr no-hover>
          <q-th
            :class="titleClickable && 'cursor-pointer'"
            :tabindex="titleClickable ? '0' : '-1'"
            @click="emit('title-click')"
          >
            {{ display.title }}
          </q-th>
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
      <template v-else><q-spinner color="primary" size="16px" /></template>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.body--dark .self-display-content-root {
  background-color: #131313;
}

.self-header {
  background-color: $grey-2;
}

.body--dark .self-header {
  background-color: #1d1d1d;
}
</style>
