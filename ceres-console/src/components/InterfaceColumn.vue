<script lang="ts" setup>
import { ColumnElement, ComponentInfo } from '@/api/models'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'
import { StyleValue } from 'vue'

const { element } = defineProps<{
  component: ComponentInfo
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
    <div v-for="(child, i) in element.children" :key="i" :class="childClass" :style="style">
      <interface-element
        class="full-width"
        :component="component"
        :element="child"
        :path="[...path, i]"
      />
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
