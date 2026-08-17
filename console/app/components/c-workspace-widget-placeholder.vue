<script lang="ts" setup>
import type { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()
</script>

<!-- Drawn where the widget in hand would land, sized and placed exactly as it would be, so the
layout on screen is the one letting go would leave behind. -->
<template>
  <div
    :class="[
      'border-primary bg-primary/10 flex h-full flex-col items-center',
      'justify-center rounded border-2 border-dashed',
    ]"
  >
    <c-text class="text-primary" variant="body1">
      {{ widget.name }}
    </c-text>
  </div>
</template>
