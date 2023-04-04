<script setup lang="ts">
import type { ComponentInfo, LayoutNode } from '@/api/models'
import Display from '@/components/Display.vue'

const { node } = defineProps<{
  component: ComponentInfo
  node: LayoutNode
}>()
</script>

<template>
  <display
    v-if="node.kind === 'display'"
    :component="component"
    :display="node"
    :procedure-name="node.procedure"
  />
  <div v-else-if="node.kind === 'row'" class="q-col-gutter-sm row">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component="component" :node="child" />
    </div>
  </div>
  <div v-else-if="node.kind === 'column'" class="column q-col-gutter-sm">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component="component" :node="child" />
    </div>
  </div>
</template>
