<script setup lang="ts">
import type { ComponentInfo, LayoutNode } from '@/api/models'
import LayoutButton from '@/components/LayoutButton.vue'
import LayoutCarousel from '@/components/LayoutCarousel.vue'
import LayoutDisplay from '@/components/LayoutDisplay.vue'
import { LayoutPath } from '@/layout'

const { node } = defineProps<{
  component: ComponentInfo
  node: LayoutNode
  path: LayoutPath
}>()
</script>

<template>
  <layout-display
    v-if="node.kind === 'display'"
    :component="component"
    :display="node"
    :path="path"
  />
  <layout-button v-if="node.kind === 'button'" :button="node" :component="component" />
  <div v-else-if="node.kind === 'row'" class="q-col-gutter-sm row">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component="component" :node="child" :path="[...path, i]" />
    </div>
  </div>
  <div v-else-if="node.kind === 'column'" class="column q-col-gutter-sm">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component="component" :node="child" :path="[...path, i]" />
    </div>
  </div>
  <div v-else-if="node.kind === 'carousel'">
    <layout-carousel :component="component" :node="node" :path="path" />
  </div>
</template>
