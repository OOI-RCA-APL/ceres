<script lang="ts" setup>
import { DisplayElement, Element } from '@/api/elements'
import { useEngine } from '@/api/engine'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const { element, path } = defineProps<{
  element: DisplayElement
  path: InterfacePath
}>()

const engine = useEngine()

let rendered: Element | null = $shallowRef(null)

engine.systems.useElementStream(element.address, element.query, {}, (current) => {
  rendered = current
})
</script>

<template>
  <interface-element v-if="rendered" :element="rendered" :path />
</template>
