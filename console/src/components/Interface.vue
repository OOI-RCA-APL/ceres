<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { isError } from '@/api/shared'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { useInterfaceContext } from '@/interface'

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
  <interface-element v-if="result != null && !isError(result)" :element="result" :path="[]" />
</template>
