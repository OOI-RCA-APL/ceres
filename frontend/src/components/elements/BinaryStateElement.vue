<template>
  <q-chip :color="color" :label="valueText" size="lg" square text-color="white" />
</template>

<script lang="ts" setup>
import { BinaryStateElementInfo } from '@/element'

const { info } = defineProps<{
  info: BinaryStateElementInfo
}>()

const valueText = $computed(() => `${info.value ? info.trueText : info.falseText}`)
const color = $computed(() => (info.value ? info.trueColor : info.falseColor) as string)
</script>
