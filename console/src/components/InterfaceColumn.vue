<script lang="ts" setup>
import { StyleValue } from 'vue'

import { ColumnElement } from '@/api/elements'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const { element } = defineProps<{
  element: ColumnElement
  path: InterfacePath
}>()

const style = $computed<StyleValue>(() => ({
  justifyContent: element.justify,
  alignContent: element.align,
}))

const childClass = $computed(() => {
  if (element.sizing === 'grow') {
    return 'col'
  }
  if (element.sizing === 'shrink') {
    return 'col-auto'
  }

  return undefined
})
</script>

<template>
  <div :class="$style.root">
    <div v-for="(child, i) in element.children" :key="i" :class="childClass" :style>
      <interface-element class="full-width" :element="child" :path="[...path, i]" />
    </div>
  </div>
</template>

<style module>
.root {
  display: flex;
  flex-direction: column;
}

.root > *:not(:last-child) {
  padding-bottom: 8px;
}
</style>
