<script lang="ts" setup>
import type { TextElement } from '@/api/elements'
import CommonText from '@/components/CommonText.vue'

const { element } = defineProps<{
  element: TextElement
}>()

const color = $computed(() => element.color ?? undefined)
</script>

<template>
  <common-text :style="{ color }" :variant="element.variant">{{ element.value }}</common-text>
</template>
