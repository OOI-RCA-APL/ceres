<template>
  <common-text :style="{ color }" variant="title2">{{ text }}</common-text>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { ValueDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: ValueDisplayInfo
}>()

const text = $computed(() => (info.unit ? `${info.value}${info.unit}` : `${info.value}`))
const color = $computed(() => info.color ?? undefined)
</script>
