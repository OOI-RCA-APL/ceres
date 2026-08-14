<script lang="ts">
/** Height of the application header, which every page header pins beneath. */
export const appHeaderHeight = 50

/** Height of a page header, mirroring the header band below. */
export const pageHeaderHeight = 42

/** Height of a dense page header, mirroring the dense band below. */
export const densePageHeaderHeight = 32
</script>

<script lang="ts" setup>
const {
  title,
  dense = false,
  fill = false,
  noHeader = false,
  stickyTop = appHeaderHeight,
} = defineProps<{
  title?: string
  dense?: boolean
  fill?: boolean

  /** Renders no header band at all, for a page whose chrome lives on its host. */
  noHeader?: boolean

  /** Where the header pins as the page scrolls under it.

  Defaults to sitting directly beneath the application header. A page nested inside another
  raises this by the height of the headers above it, so the two stack rather than overlap.
  */
  stickyTop?: number
}>()
</script>

<template>
  <div class="relative" :class="fill && $style.fillRoot">
    <!-- The header and the rule under it travel together, so the rule does not scroll out from
    beneath the header it belongs to. Pinned rather than fixed, so a page nested in another still
    lays its header out in flow and only pins once it reaches the one above. -->
    <div v-if="!noHeader" class="sticky z-[3] bg-default" :style="{ top: `${stickyTop}px` }">
      <div
        class="flex items-center"
        :style="{ height: `${dense ? densePageHeaderHeight : pageHeaderHeight}px` }"
      >
        <c-text v-if="title != null" class="ml-4" variant="title2">
          {{ title }}
        </c-text>
        <slot name="header-append" />
      </div>
      <c-separator />
    </div>
    <slot />
  </div>
</template>

<style module>
/* Fill what is left of the viewport under the app header, so a page can push trailing content to
the bottom with `margin-top: auto` instead of letting it float mid-page. */
.fillRoot {
  display: flex;
  min-height: calc(100vh - 50px);
  flex-direction: column;
}
</style>
