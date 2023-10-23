<script lang="ts" setup>
import { ValueElement } from '@/api/models'
import CommonText from '@/components/CommonText.vue'

const { element } = defineProps<{
  element: ValueElement
}>()

const text = $computed(() =>
  element.unit ? `${element.value}${element.unit}` : `${element.value}`
)
const color = $computed(() => element.color ?? undefined)
</script>

<template>
  <common-text :style="{ color }" variant="title2">{{ text }}</common-text>
</template>
