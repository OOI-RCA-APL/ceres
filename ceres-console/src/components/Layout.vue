<script setup lang="ts">
import { ComponentInfo } from '@/api/models'
import { getLayout, useQuery } from '@/api/operations'
import LayoutNode from '@/components/LayoutNode.vue'
import { computed } from 'vue'

const { component } = defineProps<{
  component: ComponentInfo
}>()

const query = useQuery(['getLayout', computed(() => component.address)], async () => {
  return await getLayout(component.address)
})

await query.suspense()
</script>

<template>
  <layout-node
    v-if="query.data.value?.ok"
    :component="component"
    :node="query.data.value.value.body"
  />
</template>
