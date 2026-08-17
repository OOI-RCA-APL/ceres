<script lang="ts" setup>
import type { ParticlesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ParticlesWidget
}>()

const columns = [
  { label: 'Type', name: 'type', minWidth: 52 },
  { label: 'Data', name: 'data' },
]
</script>

<template>
  <c-record-view :columns="columns" :widget />
</template>
