<script lang="ts" setup>
import { useAttrs } from 'vue'

import { NuxtLink } from '#components'

const {
  to = null,
  disabled = false,
  selectable = false,
} = defineProps<{
  /** Where the row leads, which makes it a link. */
  to?: string | null
  /** Only reaches a row that does something, a link having nothing to disable. */
  disabled?: boolean
  /** Whether the row's click picks it out of the list rather than acting. Such a row stays a
  plain element, a button being able to hold only one line of phrasing and taking a stop in
  the tab order that a list of them would fill. */
  selectable?: boolean
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

  return attrs.onClick == null || selectable ? 'div' : 'button'
})

const isButton = $computed(() => element === 'button')

const isPressable = $computed(() => element !== 'div' || selectable)
</script>

<template>
  <component
    :is="element"
    class="flex items-center gap-2 px-3 py-1"
    :class="[
      isPressable && 'hover:bg-elevated w-full text-left disabled:opacity-50',
      // Held back for a selectable row, whose click picks it out of the list rather than acting.
      isPressable && !selectable && 'cursor-pointer',
    ]"
    :disabled="isButton ? disabled : undefined"
    :to="to ?? undefined"
    :type="isButton ? 'button' : undefined"
  >
    <slot />
  </component>
</template>
