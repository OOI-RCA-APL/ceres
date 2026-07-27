<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

const { title, dense = false } = defineProps<{
  title?: string
  dense?: boolean
}>()
</script>

<template>
  <div :class="$style.root">
    <div :class="[$style.header, dense && $style.denseHeader, 'items-center', 'row']">
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

// A header whose content is a tab strip rather than a title reads better shorter, since the tabs
// fill it edge to edge and would otherwise tower over the page beneath them.
.denseHeader {
  height: 32px !important;
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
