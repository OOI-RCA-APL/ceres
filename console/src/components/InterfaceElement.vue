<script setup lang="ts">
import type { Element, ElementType } from '@/api/elements'
import InterfaceButton from '@/components/InterfaceButton.vue'
import InterfaceCarousel from '@/components/InterfaceCarousel.vue'
import InterfaceChart from '@/components/InterfaceChart.vue'
import InterfaceColumn from '@/components/InterfaceColumn.vue'
import InterfaceDisplay from '@/components/InterfaceDisplay.vue'
import InterfaceGauge from '@/components/InterfaceGauge.vue'
import InterfaceRow from '@/components/InterfaceRow.vue'
import InterfaceState from '@/components/InterfaceState.vue'
import InterfaceValue from '@/components/InterfaceValue.vue'
import { InterfacePath } from '@/interface'
import { ComponentConstructor } from 'quasar'

const componentClasses: Readonly<Record<ElementType, ComponentConstructor>> = {
  button: InterfaceButton,
  row: InterfaceRow,
  column: InterfaceColumn,
  carousel: InterfaceCarousel,
  value: InterfaceValue,
  state: InterfaceState,
  gauge: InterfaceGauge,
  chart: InterfaceChart,
  display: InterfaceDisplay,
}

const { element, path } = defineProps<{
  element: Element
  path: InterfacePath
}>()

const componentClass = $computed<ComponentConstructor | null>(
  () => componentClasses[element.type] ?? null
)

const componentProps = $computed(() => ({
  element,
  path,
}))
</script>

<template>
  <component :is="componentClass" v-if="componentClass" v-bind="componentProps" />
</template>
