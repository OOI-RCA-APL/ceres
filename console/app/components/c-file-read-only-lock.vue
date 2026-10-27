<script lang="ts" setup>
import icons from '@/icons'

const { raised = false, active = false } = defineProps<{
  /** Lifts the lock 3px above the name's top, so a crumb line from its top clears the names. */
  raised?: boolean
  /** Takes the name's own color, as the current crumb's, instead of a dimmed one. */
  active?: boolean
}>()
</script>

<template>
  <!-- Set against the top of the name it follows, like a superscript badge. -->
  <c-tooltip text="You can view but not change this mount.">
    <c-icon
      class="-ml-1 size-2.5 shrink-0 self-start"
      :class="[raised && '-translate-y-[3px]', !active && 'text-dimmed']"
      data-read-only-lock
      :name="icons.locked"
    />
  </c-tooltip>
</template>
