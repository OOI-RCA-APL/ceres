<script lang="ts">
export type FileInfoDialogProps = {
  /** The ID of the mount holding the entry. */
  mount: string
  /** The entry's path under the mount, empty for the mount itself. */
  path: string[]
  /** The name the entry shows under. */
  name: string
  /** What holds the entry, outermost first: its component, its mount, and each directory. */
  location: string[]
  /** Whether the caller may change entries under the mount. */
  writable: boolean
}
</script>

<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { fileInfoRows, fileStatQueryKey } from '@/api/files'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { copyText } from '@/utilities'

const { mount, path, name, location, writable } = defineProps<FileInfoDialogProps>()

const emit = defineEmits<{ close: [false] }>()

const engine = useEngine()
const notify = useNotify()

const statQuery = useQuery({
  queryKey: fileStatQueryKey(mount, path),
  queryFn: () => engine.files.stat(mount, path),
})

const rows = $computed(() => {
  const stat = statQuery.data.value
  return stat == null ? [] : fileInfoRows(stat, { name, location, writable })
})

async function copy(value: string) {
  await copyText(value)
  notify.success('Path copied to clipboard.')
}
</script>

<template>
  <c-modal title="Info" @update:open="(open: boolean) => open || emit('close', false)">
    <template #body>
      <p v-if="statQuery.isError.value" class="text-muted">
        The engine could not describe this entry.
      </p>
      <p v-else-if="statQuery.isPending.value" class="text-muted">Loading&hellip;</p>
      <dl v-else class="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <template v-for="row in rows" :key="row.label">
          <dt class="text-muted">{{ row.label }}</dt>
          <dd class="flex min-w-0 items-center gap-1">
            <span class="break-all">{{ row.value }}</span>
            <c-button
              v-if="row.copyable"
              aria-label="Copy"
              color="neutral"
              :icon="icons.copy"
              size="xs"
              variant="ghost"
              @click="copy(row.value)"
            />
          </dd>
        </template>
      </dl>
    </template>
    <template #footer>
      <div class="flex w-full justify-end">
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">Close</c-button>
      </div>
    </template>
  </c-modal>
</template>
