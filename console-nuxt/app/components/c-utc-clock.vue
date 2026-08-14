<script lang="ts" setup>
import { useTime } from '@/time'

const time = useTime()
</script>

<template>
  <div class="flex items-end gap-1">
    <c-text element="span" variant="title2">{{ time.now.format('H:mm') }}</c-text>
    <c-text class="opacity-75" element="span" variant="body2">UTC</c-text>
  </div>
</template>
