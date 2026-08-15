<script lang="ts" setup>
import type { AlertsWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: AlertsWidget
}>()

const columns = [
  { label: 'Level', name: 'level', minWidth: 56 },
  { label: 'Type', name: 'type', minWidth: 52 },
  { label: 'Data', name: 'data' },
]
</script>

<template>
  <c-record-view :columns="columns" :widget />
</template>
