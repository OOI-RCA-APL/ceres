<script setup lang="ts">
import icons from '@/icons'

defineEmits<{
  click: []
}>()

// Compact drops the button's own padding, which is taller than the row it sits in there and would
// otherwise push out past the field's edge.
defineProps<{
  compact?: boolean
}>()
</script>

<template>
  <c-button
    color="neutral"
    :icon="icons.clear"
    size="xs"
    square
    :ui="compact ? { base: 'p-0' } : undefined"
    variant="ghost"
    @click.stop.prevent="$emit('click')"
  />
</template>
