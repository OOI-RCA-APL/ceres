<script setup lang="ts">
import { Address } from '@/address'
import type { LayoutNode } from '@/api/models'
import Display from '@/components/Display.vue'

const { node } = defineProps<{
  address: Address
  node: LayoutNode
}>()
</script>

<template>
  <display
    v-if="node.kind === 'display'"
    :address="address"
    :display="node"
    :procedure-name="node.procedure"
  />
  <div v-else-if="node.kind === 'row'" class="q-col-gutter-sm row">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :address="address" :node="child" />
    </div>
  </div>
  <div v-else-if="node.kind === 'column'" class="column q-col-gutter-sm">
    <div v-for="(child, i) in node.children" :key="i" class="col">
      <layout-node :address="address" :node="child" />
    </div>
  </div>
</template>
