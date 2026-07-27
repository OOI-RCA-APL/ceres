<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

const { title, dense = false, fill = false } = defineProps<{
  title?: string
  dense?: boolean
  fill?: boolean
}>()
</script>

<template>
  <div :class="[$style.root, fill && $style.fillRoot]">
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

// Fill what is left of the viewport under the app header, so a page can push trailing content to
// the bottom with `margin-top: auto` instead of letting it float mid-page.
.fillRoot {
  display: flex;
  min-height: calc(100vh - 50px);
  flex-direction: column;
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
