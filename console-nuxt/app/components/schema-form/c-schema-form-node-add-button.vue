<script setup lang="ts">
import icons from '@/icons'

defineEmits<{
  click: []
}>()
</script>

<template>
  <c-button
    color="neutral"
    :icon="icons.add"
    size="xs"
    square
    variant="ghost"
    @click="$emit('click')"
  />
</template>
