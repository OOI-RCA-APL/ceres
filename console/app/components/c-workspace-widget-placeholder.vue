<script lang="ts" setup>
import type { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()
</script>

<!-- Drawn where the widget in hand would land, sized and placed exactly as it would be, so the
layout on screen is the one letting go would leave behind. -->
<template>
  <div class="flex h-full flex-col items-center justify-center" :class="$style.root">
    <c-text class="text-primary" variant="body1">
      {{ widget.name }}
    </c-text>
  </div>
</template>

<style module>
.root {
  border: 2px dashed var(--ui-primary);
  border-radius: 4px;
  background-color: color-mix(in srgb, var(--ui-primary) 10%, transparent);
}
</style>
