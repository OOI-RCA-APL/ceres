<template>
  <gauge-element :element="element" />
</template>

<script lang="ts" setup>
import type { ElementInfo } from '../mock'
import GaugeElement from './elements/GaugeElement.vue'

defineProps<{
  element: ElementInfo
}>()
</script>
