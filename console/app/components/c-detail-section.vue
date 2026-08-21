<script lang="ts" setup>
import icons from '@/icons'

defineProps<{
  title: string
}>()

let expanded = $(defineModel<boolean>('expanded', { default: false }))
</script>

<!-- One expandable block of a component's reference lists. Carries no border of its own so a
caller can stack several inside one frame. -->
<template>
  <div class="flex min-h-0 flex-col" :class="$style.section">
    <button
      class="hover:bg-elevated flex w-full flex-none items-center gap-1 px-3 py-1 text-left"
      :class="[$style.header, !expanded && $style.closed]"
      type="button"
      @click="expanded = !expanded"
    >
      <c-text variant="title3">{{ title }}</c-text>
      <div class="flex-1" />
      <c-icon :name="expanded ? icons.menuUp : icons.menuDown" size="18" />
    </button>
    <div v-if="expanded" class="min-h-0 grow overflow-auto pb-2">
      <slot />
    </div>
  </div>
</template>

<style module>
/* A header meeting the frame's corner takes that corner's rounding, or its hover fill stands
proud of a border that has already curved away beside it. Inset by the frame's own border, so
the fill stops exactly against it. */
.section:first-child .header {
  border-start-start-radius: calc(var(--ui-radius) * 1.5 - 1px);
  border-start-end-radius: calc(var(--ui-radius) * 1.5 - 1px);
}

/* Only while closed, since an open section's content is what reaches the bottom corner. */
.section:last-child .header.closed {
  border-end-start-radius: calc(var(--ui-radius) * 1.5 - 1px);
  border-end-end-radius: calc(var(--ui-radius) * 1.5 - 1px);
}
</style>
