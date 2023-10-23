<script setup lang="ts">
import { ComponentInfo } from '@/api/models'
import { render, useQuery } from '@/api/operations'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { computed } from 'vue'

const { component } = defineProps<{
  component: ComponentInfo
}>()

const query = useQuery(['render', computed(() => component.address)], async () => {
  return await render(component.address)
})

await query.suspense()

const result = $computed(() => query.data.value)
</script>

<template>
  <interface-element v-if="result?.ok" :component="component" :element="result.value" :path="[]" />
</template>
