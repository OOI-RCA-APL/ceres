<script lang="ts" setup>
import { ComponentInfo, RowElement } from '@/api/models'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'
import { StyleValue } from 'vue'

const { element } = defineProps<{
  component: ComponentInfo
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
  <div :class="[$style.root, '']" :style="style">
    <div v-for="(child, i) in element.children" :key="i" :class="childClass">
      <interface-element
        class="full-width"
        :component="component"
        :element="child"
        :path="[...path, i]"
      />
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
