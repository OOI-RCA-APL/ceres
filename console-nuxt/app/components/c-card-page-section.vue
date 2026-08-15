<script lang="ts" setup>
defineProps<{
  title: string
}>()
</script>

<template>
  <!-- Held to the same measure as the card above it, so the page reads as one column. -->
  <div class="border-default bg-elevated mt-4 w-full max-w-[440px] rounded-lg border">
    <c-text class="block px-4 py-2" element="h2" variant="title2">{{ title }}</c-text>
    <c-separator />
    <slot />
  </div>
</template>
