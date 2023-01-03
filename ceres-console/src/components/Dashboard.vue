<template>
  <div class="column q-gutter-sm">
    <!-- <element v-for="(info, i) in displays" :key="i" :info="info" /> -->
  </div>
</template>

<script lang="ts" setup>
// import Element from '@/components/Display.vue'
import type { DisplayInfo } from '@/display'

defineProps<{
  displays: DisplayInfo[]
}>()
</script>
