<script lang="ts" setup>
import type { Level } from '@/api/shared'

const { level } = defineProps<{
  level: Level
}>()

const color = $computed(() => {
  switch (level) {
    case 'debug':
      return 'neutral'
    case 'info':
      return 'info'
    case 'warning':
      return 'warning'
    case 'error':
    case 'critical':
      return 'error'
  }
})
</script>

<template>
  <c-badge
    :color="color"
    :ui="{ base: 'font-mono text-[8px] px-1.5 py-0 min-w-9.5 justify-center rounded-full' }"
    variant="solid"
  >
    {{ level }}
  </c-badge>
</template>
