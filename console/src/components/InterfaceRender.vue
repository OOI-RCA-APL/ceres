<script lang="ts" setup>
import { ComponentInfo, DisplayElement, Element } from '@/api/models'
import { useElementStream } from '@/api/operations'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const { component, element, path } = defineProps<{
  component: ComponentInfo
  element: DisplayElement
  path: InterfacePath
}>()

let rendered: Element | null = $shallowRef(null)

useElementStream(component.address, element.query, {}, (current) => {
  rendered = current
})
</script>

<template>
  <interface-element v-if="rendered" :component="component" :element="rendered" :path="path" />
</template>
