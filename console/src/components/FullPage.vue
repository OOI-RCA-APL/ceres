<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

defineProps<{
  title?: string
}>()
</script>

<template>
  <div :class="$style.root">
    <div :class="[$style.header, 'items-center', 'row']">
      <common-text v-if="title != null" class="q-ml-md q-py-sm" variant="title2">
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
  height: calc(100vh - 48px - 2px);
}

.header {
  height: 48px !important;
}

:global(.body--light) .root {
  background-color: $grey-2;
}

:global(.body--light) .header {
  background-color: white;
}
</style>
