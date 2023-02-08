<template>
  <layout-node :component-name="componentName" :node="layout.body" :unit-name="unitName" />
</template>

<script setup lang="ts">
import type { Layout } from '@/api/models'
import LayoutNode from '@/components/LayoutNode.vue'

const { layout } = defineProps<{
  unitName: string
  componentName: string
  layout: Layout
}>()
</script>
