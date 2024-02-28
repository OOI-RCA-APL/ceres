<script setup lang="ts">
import { Address } from '@/address'
import { useEngine } from '@/api/engine'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { useInterfaceContext } from '@/interface'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

const { address } = defineProps<{
  address: Address
}>()

useInterfaceContext(address)

const engine = useEngine()

const query = useQuery({
  queryKey: computed(() => ['render', address]),
  queryFn: async () => {
    return await engine.components.render(address)
  },
})

await query.suspense()

const result = $computed(() => query.data.value)
</script>

<template>
  <interface-element v-if="result?.ok" :element="result.value" :path="[]" />
</template>
