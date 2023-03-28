<script setup lang="ts">
import type { LayoutNode } from '@/api/models'
import Display from '@/components/Display.vue'

const { node } = defineProps<{
  unitName: string
  componentName: string
  node: LayoutNode
}>()
</script>

<template>
  <display
    v-if="node.kind === 'display'"
    :component-name="componentName"
    :display="node"
    :procedure-name="node.procedure"
    :unit-name="unitName"
  />
  <div v-else-if="node.kind === 'row'" class="q-col-gutter-sm row">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component-name="componentName" :node="child" :unit-name="unitName" />
    </div>
  </div>
  <div v-else-if="node.kind === 'column'" class="column q-col-gutter-sm">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :component-name="componentName" :node="child" :unit-name="unitName" />
    </div>
  </div>
</template>
