<template>
  <!-- The bordered, separated frame every stack of rows or sections in the console is drawn in.
  Height and scrolling come from the caller's own class, which merges onto this element. -->
  <div class="border-default divide-default divide-y rounded-md border">
    <slot />
  </div>
</template>
