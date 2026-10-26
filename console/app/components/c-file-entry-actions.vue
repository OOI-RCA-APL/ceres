<script lang="ts" setup>
import type { ContextMenuItem } from '@nuxt/ui'

import type { FileActionView } from '@/api/files'
import icons from '@/icons'

const { buttons, more } = defineProps<{
  buttons: FileActionView[]
  /** Everything else the entry offers, in groups. */
  more: ContextMenuItem[][]
}>()
</script>

<template>
  <div class="flex shrink-0 items-center">
    <c-tooltip
      v-for="action in buttons"
      :key="action.kind"
      :text="action.description == null ? action.label : `${action.label}, ${action.description}`"
    >
      <c-button
        :aria-label="action.label"
        color="neutral"
        :disabled="action.disabled"
        :icon="action.icon"
        size="xs"
        variant="ghost"
        @click="action.run"
      />
    </c-tooltip>
    <c-dropdown-menu v-if="more.length > 0" :items="more">
      <c-button
        aria-label="More Actions"
        color="neutral"
        :icon="icons.more"
        size="xs"
        variant="ghost"
      />
    </c-dropdown-menu>
  </div>
</template>
