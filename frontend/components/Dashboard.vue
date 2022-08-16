<template>
  <div>
    <element v-for="(element, i) in elements" :key="i" :element="element" />
  </div>
</template>

<script lang="ts" setup>
import type { ElementInfo } from '../mock'
import Element from './Element.vue'

defineProps<{
  elements: ElementInfo[]
}>()
</script>
