<script lang="ts" setup>
import icons from '@/icons'
</script>

<template>
  <!-- Raised against the name it follows, like a superscript badge. -->
  <c-tooltip text="You can view but not change this mount.">
    <c-icon class="text-dimmed -ml-1 size-2.5 shrink-0 self-start" :name="icons.locked" />
  </c-tooltip>
</template>
