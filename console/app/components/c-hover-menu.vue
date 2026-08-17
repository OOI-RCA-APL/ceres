<script lang="ts" setup>
import type { PopoverProps } from '@nuxt/ui'
import { inject, onScopeDispose, provide, reactive, watch } from 'vue'

import { hoverMenuKey } from '@/hover-menu'

const {
  openDelay = 0,
  closeDelay = 250,
  disabled = false,
} = defineProps<{
  content?: PopoverProps['content']
  ui?: PopoverProps['ui']
  openDelay?: number

  /** How long the pointer has to reach a submenu, or come back, before the menu closes. */
  closeDelay?: number

  /** Held shut, for a menu whose actions the viewer has no permission to run. */
  disabled?: boolean
}>()

const parent = inject(hoverMenuKey, null)
const identity = Symbol('hover-menu')

let isOpen = $ref(false)
let isPointerInside = $ref(false)
const heldChildren = reactive(new Set<symbol>())

function setHeld(child: symbol, held: boolean) {
  if (held) {
    heldChildren.add(child)
  } else {
    heldChildren.delete(child)
  }
}

provide(hoverMenuKey, { setHeld })

/** Whether the pointer is in this menu or in any menu opened from it. */
const isHeld = $computed(() => isPointerInside || heldChildren.size > 0)

let closeTimer = $ref<ReturnType<typeof setTimeout> | null>(null)

watch(
  () => isHeld,
  (held) => {
    parent?.setHeld(identity, held)

    if (closeTimer != null) {
      clearTimeout(closeTimer)
      closeTimer = null
    }

    if (held) {
      isOpen = true
      return
    }

    closeTimer = setTimeout(() => {
      isOpen = false
      closeTimer = null
    }, closeDelay)
  },
)

onScopeDispose(() => {
  if (closeTimer != null) {
    clearTimeout(closeTimer)
  }

  parent?.setHeld(identity, false)
})
</script>

<template>
  <!-- The popover reports where the pointer is and places the menu, while the open state is held
  here. Its own grace area spans only this menu's trigger and content, so it calls for a close
  repeatedly the whole time the pointer is in a submenu. -->
  <c-popover
    :close-delay="0"
    :content
    enable-touch
    mode="hover"
    :open="disabled ? false : isOpen"
    :open-delay="openDelay"
    :ui
    @update:open="(value: boolean) => (isPointerInside = value)"
  >
    <slot />
    <template #content>
      <div @pointerenter="isPointerInside = true" @pointerleave="isPointerInside = false">
        <slot name="content" />
      </div>
    </template>
  </c-popover>
</template>
