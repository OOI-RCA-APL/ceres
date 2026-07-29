<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()
</script>

<template>
  <div :class="[$style.root, 'column', 'full-height', 'items-center', 'justify-center']">
    <common-text :class="$style.name" variant="th">
      {{ widget.name }}
    </common-text>
  </div>
</template>

<style lang="scss" module>
// Drawn where the widget in hand would land, sized and placed exactly as it would be, so the
// layout on screen is the one letting go would leave behind.
.root {
  border: 2px dashed $primary;
  border-radius: 4px;
  background-color: rgba($primary, 0.1);
}

.name {
  color: $primary;
}
</style>
