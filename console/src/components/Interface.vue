<script setup lang="ts">
import { Address } from '@/address'
import { render, useQuery } from '@/api/operations'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { useInterfaceContext } from '@/interface'
import { computed } from 'vue'

const { address } = defineProps<{
  address: Address
}>()

useInterfaceContext(address)

const query = useQuery(['render', computed(() => address)], async () => {
  return await render(address)
})

await query.suspense()

const result = $computed(() => query.data.value)
</script>

<template>
  <interface-element v-if="result?.ok" :element="result.value" :path="[]" />
</template>
