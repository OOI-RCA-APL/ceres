<script lang="ts" setup>
import { ComponentConstructor } from 'quasar'

import type { Element, ElementType } from '@/api/elements'
import InterfaceButton from '@/components/InterfaceButton.vue'
import InterfaceCarousel from '@/components/InterfaceCarousel.vue'
import InterfaceChart from '@/components/InterfaceChart.vue'
import InterfaceColumn from '@/components/InterfaceColumn.vue'
import InterfaceDisplay from '@/components/InterfaceDisplay.vue'
import InterfaceGauge from '@/components/InterfaceGauge.vue'
import InterfaceHTML from '@/components/InterfaceHTML.vue'
import InterfaceRow from '@/components/InterfaceRow.vue'
import InterfaceState from '@/components/InterfaceState.vue'
import InterfaceText from '@/components/InterfaceText.vue'
import { InterfacePath } from '@/interface'

const componentClasses: Readonly<Record<ElementType, ComponentConstructor>> = {
  button: InterfaceButton,
  carousel: InterfaceCarousel,
  chart: InterfaceChart,
  column: InterfaceColumn,
  display: InterfaceDisplay,
  gauge: InterfaceGauge,
  html: InterfaceHTML,
  row: InterfaceRow,
  state: InterfaceState,
  text: InterfaceText,
}

const { element, path } = $defineProps<{
  element: Element
  path: InterfacePath
}>()

const componentClass = $computed<ComponentConstructor | null>(
  () => componentClasses[element.type] ?? null
)

const componentCssClass = $computed(() => element.css_class ?? undefined)
const componentCssStyle = $computed(() => element.css_style ?? undefined)
</script>

<template>
  <component
    :is="componentClass"
    v-if="componentClass"
    :class="componentCssClass"
    :element
    :path
    :style="componentCssStyle"
  />
</template>
