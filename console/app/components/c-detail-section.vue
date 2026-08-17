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
  <div class="flex min-h-0 flex-col">
    <button
      class="hover:bg-elevated flex w-full flex-none items-center gap-1 px-3 py-1 text-left"
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
