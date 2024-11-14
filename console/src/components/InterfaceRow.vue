<script lang="ts" setup>
import { StyleValue } from 'vue'

import { RowElement } from '@/api/elements'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const { element } = $defineProps<{
  element: RowElement
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
  <div :class="[$style.root, '']" :style>
    <div v-for="(child, i) in element.children" :key="i" :class="childClass">
      <interface-element class="full-width" :element="child" :path="[...path, i]" />
    </div>
  </div>
</template>

<style lang="scss" module>
.root {
  display: flex;
  flex-direction: row;
}

.root > *:not(:last-child) {
  padding-right: 8px;
}
</style>
