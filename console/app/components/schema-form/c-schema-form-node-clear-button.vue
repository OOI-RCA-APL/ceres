<script setup lang="ts">
import icons from '@/icons'

defineEmits<{
  click: []
}>()

// Embedded drops the button's own padding, which is taller than the row it sits in there and would
// otherwise push out past the field's edge, and takes the icon down to the size of the controls it
// sits beside.
defineProps<{
  embedded?: boolean
}>()
</script>

<template>
  <!-- Centered here rather than by each row that holds one, the button sitting beside fields of
  several heights. -->
  <c-button
    class="self-center"
    color="neutral"
    :icon="icons.clear"
    size="xs"
    square
    :ui="embedded ? { base: 'p-0', leadingIcon: 'size-3' } : undefined"
    variant="ghost"
    @click.stop.prevent="$emit('click')"
  />
</template>
