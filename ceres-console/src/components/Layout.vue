<script setup lang="ts">
import { Address } from '@/address'
import { getLayout, useQuery } from '@/api/operations'
import LayoutNode from '@/components/LayoutNode.vue'
import { computed } from 'vue'

const { address } = defineProps<{
  address: Address
}>()

const query = useQuery(['getLayout', computed(() => address)], async () => {
  return await getLayout(address)
})

await query.suspense()
</script>

<template>
  <layout-node v-if="query.data.value?.ok" :address="address" :node="query.data.value.value.body" />
</template>
