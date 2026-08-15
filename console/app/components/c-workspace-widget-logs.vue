<script lang="ts" setup>
import type { LogsWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: LogsWidget
}>()

const columns = [
  { label: 'Level', name: 'level', minWidth: 56 },
  { label: 'Content', name: 'content' },
]
</script>

<template>
  <c-record-view :columns="columns" :widget />
</template>
