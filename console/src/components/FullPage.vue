<script lang="ts">
/** Height of the application header, which every page header pins beneath. */
export const appHeaderHeight = 50

/** Height of a page header, mirroring `.header` below. */
export const pageHeaderHeight = 42

/** Height of a dense page header, mirroring `.denseHeader` below. */
export const densePageHeaderHeight = 32
</script>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'

const {
  title,
  dense = false,
  fill = false,
  stickyTop = appHeaderHeight,
} = defineProps<{
  title?: string
  dense?: boolean
  fill?: boolean

  /** Where the header pins as the page scrolls under it.

  Defaults to sitting directly beneath the application header. A page nested inside another
  raises this by the height of the headers above it, so the two stack rather than overlap.
  */
  stickyTop?: number
}>()
</script>

<template>
  <div :class="[$style.root, fill && $style.fillRoot]">
    <div :class="$style.headerStack" :style="{ top: `${stickyTop}px` }">
      <div :class="[$style.header, dense && $style.denseHeader, 'items-center', 'row']">
        <common-text v-if="title != null" class="q-ml-md" variant="title2">
          {{ title }}
        </common-text>
        <slot name="header-append" />
      </div>
      <q-separator />
    </div>
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

// The header and the rule under it travel together, so the rule does not scroll out from beneath
// the header it belongs to. Pinned rather than fixed, so a page nested in another still lays its
// header out in flow and only pins once it reaches the one above.
.headerStack {
  position: sticky;
  z-index: 3;
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
