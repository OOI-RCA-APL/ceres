<script lang="ts" setup>
defineProps<{
  label: string
  description?: string
}>()
</script>

<template>
  <div class="flex items-center gap-6 px-4 py-3">
    <div class="flex min-w-0 grow flex-col gap-0.5">
      <c-text variant="body2">{{ label }}</c-text>
      <c-text v-if="description" variant="description">{{ description }}</c-text>
    </div>
    <div class="flex shrink-0 items-center">
      <slot />
    </div>
  </div>
</template>
