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
</script>

<template>
  <div class="column q-col-gutter-sm">
    <div v-for="(child, i) in element.children" :key="i" class="col" :style="style">
      <interface-element :component="component" :element="child" :path="[...path, i]" />
    </div>
  </div>
</template>
