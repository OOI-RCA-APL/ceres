<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileMount,
  childComponentFolders,
  fileComponentFolderName,
  filesPlacePath,
  filePlace,
} from '@/api/files'
import icons from '@/icons'

const { root = null, linked = true } = defineProps<{
  /** The component whose folder this lists, its own mounts then its subcomponents' folders, the
  top of the list with the project's own mounts when null. */
  root?: string | null
  /** Whether each row links to its page, rather than emitting `open` or `openFolder`. */
  linked?: boolean
}>()

const emit = defineEmits<{
  open: [mount: FileMount]
  openFolder: [component: string]
}>()

defineSlots<{
  /** What shows when nothing is listed. */
  empty?: () => unknown
}>()

const engine = useEngine()

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})

const folders = $computed(() => childComponentFolders(mountsQuery.data.value ?? [], root))

const mounts = $computed(() =>
  (mountsQuery.data.value ?? [])
    .filter((current) => current.component === root)
    .sort((left, right) => left.label.localeCompare(right.label)),
)
</script>

<template>
  <slot
    v-if="mountsQuery.isSuccess.value && folders.length === 0 && mounts.length === 0"
    name="empty"
  >
    <c-text class="text-muted" variant="body3">
      {{
        engine.auth.user?.admin
          ? 'No file mounts are set up.'
          : 'No file mounts are shared with you.'
      }}
    </c-text>
  </slot>
  <div v-else-if="folders.length > 0 || mounts.length > 0" class="flex flex-col gap-3">
    <section v-if="mounts.length > 0" class="flex flex-col gap-1">
      <c-text class="text-muted px-1" variant="th">
        {{ root ?? 'Project' }}
      </c-text>
      <c-list>
        <c-file-mount
          v-for="current in mounts"
          :key="current.id"
          :linked
          :mount="current"
          @click="emit('open', current)"
        />
      </c-list>
    </section>
    <section v-if="folders.length > 0" class="flex flex-col gap-1">
      <c-text class="text-muted px-1" variant="th">Components</c-text>
      <c-list>
        <c-list-item
          v-for="folder in folders"
          :key="folder"
          :to="linked ? filesPlacePath(filePlace(null, [], folder)) : null"
          @click="emit('openFolder', folder)"
        >
          <c-icon class="shrink-0" :name="icons.components" size="16" />
          <c-text class="min-w-0 flex-1 truncate" variant="body3">
            {{ fileComponentFolderName(folder) }}
          </c-text>
        </c-list-item>
      </c-list>
    </section>
  </div>
</template>
