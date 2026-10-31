<script lang="ts" setup>
import icons from '@/icons'

const { active = false } = defineProps<{
  /** Takes the name's own color, as the current crumb's, instead of a dimmed one. */
  active?: boolean
}>()
</script>

<template>
  <!-- Set against the top of the name it follows, like a superscript badge. -->
  <c-tooltip text="You can view but not change this mount.">
    <c-icon
      class="-ml-1 size-2.5 shrink-0 self-start"
      :class="!active && 'text-dimmed'"
      :name="icons.locked"
    />
  </c-tooltip>
</template>
