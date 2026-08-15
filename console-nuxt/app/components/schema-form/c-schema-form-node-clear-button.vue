<script setup lang="ts">
import icons from '@/icons'

defineEmits<{
  click: []
}>()
</script>

<template>
  <c-button
    color="neutral"
    :icon="icons.clear"
    size="xs"
    square
    variant="ghost"
    @click.stop.prevent="$emit('click')"
  />
</template>
