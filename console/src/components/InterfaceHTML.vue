<script lang="ts" setup>
import type { HTMLElement } from '@/api/elements'

const { element } = $defineProps<{
  element: HTMLElement
}>()
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div :class="$style.root" v-html="element.value" />
</template>

<style lang="scss" module>
.root {
  display: contents;
}
</style>
