<script setup lang="ts">
import { getLayout, useQuery } from '@/api/operations'
import LayoutNode from '@/components/LayoutNode.vue'

const { unitName, componentName } = defineProps<{
  unitName: string
  componentName: string
}>()

const query = useQuery(['getLayout', unitName, componentName], async () => {
  return await getLayout(unitName, componentName)
})

await query.suspense()
</script>

<template>
  <layout-node
    v-if="query.data.value?.ok"
    :component-name="componentName"
    :node="query.data.value.value.body"
    :unit-name="unitName"
  />
</template>
