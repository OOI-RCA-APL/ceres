<template>
  <!-- The bordered, separated frame every stack of rows or sections in the console is drawn in.
  Height and scrolling come from the caller's own class, which merges onto this element. -->
  <div class="border-default divide-default divide-y rounded-md border" :class="$style.list">
    <slot />
  </div>
</template>

<style module>
/* The rows at either end meet the frame's corners, so they take that rounding or a filled one
stands proud of a border that has already curved away beside it. Rounded rather than clipped,
because a row being dragged out of the frame to reorder has to stay visible. */
.list > :first-child {
  border-start-start-radius: calc(var(--ui-radius) * 1.5 - 1px);
  border-start-end-radius: calc(var(--ui-radius) * 1.5 - 1px);
}

.list > :last-child {
  border-end-start-radius: calc(var(--ui-radius) * 1.5 - 1px);
  border-end-end-radius: calc(var(--ui-radius) * 1.5 - 1px);
}
</style>
