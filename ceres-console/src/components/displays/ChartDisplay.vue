<template>
  <chart autoresize :option="info.value" :style="{ height: `${info.height}px` }" />
</template>

<script lang="ts" setup>
import { ChartDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: ChartDisplayInfo
}>()
</script>
