<script lang="ts" setup>
import { DisplayElement, Element } from '@/api/models'
import { useElementStream } from '@/api/operations'
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
