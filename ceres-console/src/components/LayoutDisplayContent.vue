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
  isLoading = false,
} = defineProps<{
  display: LayoutDisplay
  info: DisplayInfo | null
  titleClickable?: boolean
  isLoading?: boolean
}>()

const emit = defineEmits<{
  (emit: 'title-click'): void
}>()
</script>

<template>
  <div :class="[$style.root, 'column']">
    <q-markup-table dense flat separator="cell">
      <thead :class="$style.header">
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
    <div class="col-grow items-center justify-center q-pa-xs relative-position row">
      <template v-if="info">
        <value-display v-if="info.kind === 'value'" key="value-display" :info="info" />
        <state-display v-else-if="info.kind === 'state'" key="state-display" :info="info" />
        <gauge-display v-else-if="info.kind === 'gauge'" key="gauge-display" :info="info" />
        <chart-display v-else-if="info.kind === 'chart'" key="chart-display" :info="info" />
      </template>
      <template v-else>
        <div key="placeholder" :class="$style.placeholder" />
      </template>
      <transition appear enter-active-class="animated fadeIn" leave-active-class="animated fadeOut">
        <div :class="[$style.spinnerContainer, info != null && $style.spinnerContainerRefresh]">
          <q-spinner-orbit
            v-if="isLoading || info == null"
            key="spinner"
            :class="$style.spinner"
            color="primary"
            size="18px"
          />
        </div>
      </transition>
    </div>
  </div>
</template>

<style lang="scss" module>
:global(.dark) .root {
  background-color: #131313;
}

.header {
  background-color: $grey-2;
}

:global(.dark) .header {
  background-color: #1d1d1d;
}

.spinnerContainer {
  width: 16px;
  height: 16px;
  position: absolute;
  left: auto;
  right: auto;
  top: auto;
  bottom: auto;
}

.spinnerContainer.spinnerContainerRefresh {
  left: 4px;
  top: -26px;
}

.placeholder {
  min-height: 27px;
}
</style>
