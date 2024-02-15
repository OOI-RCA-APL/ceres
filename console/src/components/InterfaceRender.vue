<script lang="ts" setup>
import { DisplayElement, Element, useElementStream } from '@/api/elements'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const { element, path } = defineProps<{
  element: DisplayElement
  path: InterfacePath
}>()

let rendered: Element | null = $shallowRef(null)

useElementStream(element.address, element.query, {}, (current) => {
  rendered = current
})
</script>

<template>
  <interface-element v-if="rendered" :element="rendered" :path="path" />
</template>
