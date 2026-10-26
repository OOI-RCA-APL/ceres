<script lang="ts" setup>
import { type FileMount, filesPagePath } from '@/api/files'
import icons from '@/icons'

const {
  mount,
  showComponent = false,
  linked = true,
} = defineProps<{
  mount: FileMount
  /** Whether to name the component holding the mount, for a list mixing components. */
  showComponent?: boolean
  /** Whether the row links to the mount's page, rather than leaving its click to the caller. */
  linked?: boolean
}>()
</script>

<template>
  <c-list-item :to="linked ? filesPagePath(mount.id) : null">
    <c-icon class="shrink-0" :name="icons.mount" size="16" />
    <c-text class="min-w-0 flex-1 truncate" variant="body3">{{ mount.label }}</c-text>
    <c-badge
      v-if="mount.temporary"
      color="neutral"
      :icon="icons.mountTemporary"
      size="sm"
      variant="outline"
    >
      Temporary
    </c-badge>
    <c-text v-if="showComponent" class="text-muted min-w-0 truncate" variant="body3">
      {{ mount.component ?? 'Project' }}
    </c-text>
  </c-list-item>
</template>
