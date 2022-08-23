<template>
  <q-btn-toggle
    v-model="info.value"
    color="grey-5"
    :options="options"
    readonly
    :ripple="false"
    size="md"
    stack
    text-color="grey-4"
    :toggle-color="color"
  />
</template>

<script lang="ts" setup>
import { BinaryStateElementInfo } from '@/element'

const { info } = defineProps<{
  info: BinaryStateElementInfo
}>()

const color = $computed(
  () => info.options.find((state) => state.value === info.value)?.color ?? 'grey-5'
)
const options = $computed(() =>
  info.options.map((state) => ({ label: state.label, value: state.value }))
)
console.log(options)
</script>
