<script lang="ts" setup>
import { useAttrs } from 'vue'

import { NuxtLink } from '#components'

const { to = null, disabled = false } = defineProps<{
  /** Where the row leads, which makes it a link. */
  to?: string | null
  /** Only reaches a row that does something, a link having nothing to disable. */
  disabled?: boolean
}>()

const attrs = useAttrs()

// A row that goes somewhere is a link, one that does something is a button, and one that only
// shows is neither. Decided here so every list's rows carry the same geometry either way.
//
// `NuxtLink` is the imported component and not its name, since a string here resolves only against
// locally registered components and would render an unknown element that navigates nowhere.
const element = $computed(() => {
  if (to != null) {
    return NuxtLink
  }

  return attrs.onClick == null ? 'div' : 'button'
})

const isButton = $computed(() => element === 'button')
</script>

<template>
  <component
    :is="element"
    class="flex items-center gap-2 px-3 py-1"
    :class="
      element !== 'div' && 'hover:bg-elevated w-full cursor-pointer text-left disabled:opacity-50'
    "
    :disabled="isButton ? disabled : undefined"
    :to="to ?? undefined"
    :type="isButton ? 'button' : undefined"
  >
    <slot />
  </component>
</template>
