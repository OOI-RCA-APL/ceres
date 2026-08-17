<script setup lang="ts">
import icons from '@/icons'

defineEmits<{
  click: []
}>()

// Embedded drops the button's own padding, which is taller than the row it sits in there and would
// otherwise push out past the field's edge.
defineProps<{
  embedded?: boolean
}>()
</script>

<template>
  <c-button
    color="neutral"
    :icon="icons.clear"
    size="xs"
    square
    :ui="embedded ? { base: 'p-0' } : undefined"
    variant="ghost"
    @click.stop.prevent="$emit('click')"
  />
</template>
