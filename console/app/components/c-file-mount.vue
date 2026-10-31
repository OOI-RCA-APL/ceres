<script lang="ts" setup>
import { type FileMount, filesPagePath } from '@/api/files'
import icons from '@/icons'

const { mount, linked = true } = defineProps<{
  mount: FileMount
  /** Whether the row links to the mount's page, rather than leaving its click to the caller. */
  linked?: boolean
}>()
</script>

<template>
  <c-list-item :to="linked ? filesPagePath(mount.id) : null">
    <c-icon class="shrink-0" :name="icons.mount" size="16" />
    <div class="flex min-w-0 flex-1 items-center gap-1.5">
      <c-text class="min-w-0 truncate" variant="body3">{{ mount.label }}</c-text>
      <c-file-read-only-lock v-if="mount.access !== 'edit'" />
    </div>
    <c-badge
      v-if="mount.temporary"
      color="neutral"
      :icon="icons.mountTemporary"
      size="sm"
      variant="outline"
    >
      Temporary
    </c-badge>
  </c-list-item>
</template>
