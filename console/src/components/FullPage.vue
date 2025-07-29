<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

defineProps<{
  title?: string
}>()
</script>

<template>
  <div :class="$style.root">
    <div :class="[$style.header, 'items-center', 'row']">
      <common-text v-if="title != null" class="q-ml-md" variant="title2">
        {{ title }}
      </common-text>
      <slot name="header-append" />
    </div>
    <q-separator />
    <slot />
  </div>
</template>

<style lang="scss" module>
.root {
  position: relative;
}

.header {
  height: 42px !important;
}

:global(.dark) .header {
  background-color: $dark;
}

:global(.light) .root {
  background-color: $grey-2;
}

:global(.light) .header {
  background-color: white;
}
</style>
