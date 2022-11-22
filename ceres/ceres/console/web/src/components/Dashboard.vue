<template>
  <div class="column q-gutter-sm">
    <element v-for="(info, i) in elements" :key="i" :info="info" />
  </div>
</template>

<script lang="ts" setup>
import Element from '@/components/Element.vue'
import type { ElementInfo } from '@/element'

defineProps<{
  elements: ElementInfo[]
}>()
</script>
