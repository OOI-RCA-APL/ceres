<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { type FileMount, isFileMountUnder } from '@/api/files'

const { root = null, linked = true } = defineProps<{
  /** Lists only the mounts of the component at this address and those below it, every mount when
  null. */
  root?: string | null
  /** Whether each mount links to its page, rather than emitting `open`. The `empty` slot replaces
  what shows when no mount is listed. */
  linked?: boolean
}>()

const emit = defineEmits<{
  open: [mount: FileMount]
}>()

const engine = useEngine()

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})

const mounts = $computed(() =>
  (mountsQuery.data.value ?? []).filter((current) => isFileMountUnder(current, root)),
)

/** Whether the list holds mounts of more than one component, which each row then names. */
const mixed = $computed(() => new Set(mounts.map((current) => current.component)).size > 1)
</script>

<template>
  <slot v-if="mountsQuery.isSuccess.value && mounts.length === 0" name="empty">
    <c-text class="text-muted" variant="body3">
      {{
        engine.auth.user?.admin
          ? 'No file mounts are set up.'
          : 'No file mounts are shared with you.'
      }}
    </c-text>
  </slot>
  <c-list v-else-if="mounts.length > 0">
    <c-file-mount
      v-for="current in mounts"
      :key="current.id"
      :linked
      :mount="current"
      :show-component="mixed"
      @click="emit('open', current)"
    />
  </c-list>
</template>
