<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { useQueryClient } from '@tanstack/vue-query'
import { isEqual } from 'lodash-es'
import { computed } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { type FileEntry, FileWriteError, isHiddenEntry, moveDestinationBlocked } from '@/api/files'
import { answer, useDialogs } from '@/dialogs'
import icons from '@/icons'

export type FileMoveDialogProps = {
  mount: string
  /** What the breadcrumb calls the mount itself. */
  mountLabel: string
  /** The directory holding `targets`, where the dialog opens. */
  from: string[]
  targets: FileEntry[]
  /** Whether dot folders show, as they do in the browser that asked. */
  hidden: boolean
}

const { mount, mountLabel, from, targets, hidden } = defineProps<FileMoveDialogProps>()

/** Closes with where each entry that moved went, by name, or `false` when none did. */
const emit = defineEmits<{ close: [ReadonlyMap<string, string[]> | false] }>()

const engine = useEngine()
const dialogs = useDialogs()
const queryClient = useQueryClient()

const title = $computed(() => {
  const [only] = targets
  return targets.length === 1 && only != null
    ? `Move "${only.name}"`
    : `Move ${targets.length} Items`
})

let folder = $ref<string[]>([...from])
let refusal = $ref<string | null>(null)
let moving = $ref(false)

// Shares the browser's listing query, so a folder it already showed opens without a request.
const listingQuery = useQuery({
  queryKey: computed(() => ['files', 'list', mount, ...folder]),
  queryFn: () => engine.files.list(mount, folder),
})
const folders = $computed(() =>
  (listingQuery.data.value?.entries ?? []).filter(
    (entry) => entry.kind === 'directory' && (hidden || !isHiddenEntry(entry)),
  ),
)

const breadcrumbs = $computed<BreadcrumbItem[]>(() => [
  { label: mountLabel, icon: icons.mount, onClick: () => (folder = []) },
  ...folder.map((name, index) => ({
    label: name,
    onClick: () => (folder = folder.slice(0, index + 1)),
  })),
])

const blocked = $computed(() => moveDestinationBlocked(folder, from, targets))

// Everything under a folder being moved is reached only through its row, so disabling the row
// keeps the dialog out of all of it.
function isMoving(name: string) {
  return (
    isEqual(folder, from) &&
    targets.some((target) => target.kind === 'directory' && target.name === name)
  )
}

/** Where each entry already moved went, so a retry after a refusal moves only the rest. */
const moved = new Map<string, string[]>()

function close() {
  emit('close', moved.size > 0 ? moved : false)
}

async function createFolder() {
  const name = await answer(
    dialogs.fileName({ title: 'New Folder', label: 'Name', okLabel: 'Create' }),
  )
  if (name === false) {
    return
  }

  try {
    await engine.files.createDirectory(mount, [...folder, name])
    await queryClient.invalidateQueries({ queryKey: ['files', 'list', mount, ...folder] })
    folder = [...folder, name]
  } catch (error) {
    refusal = error instanceof FileWriteError ? error.message : 'The engine could not do that.'
  }
}

// One request per entry, stopping at the first refusal so its sentence stays in view.
async function submit() {
  moving = true
  refusal = null
  try {
    for (const target of targets.filter((current) => !moved.has(current.name))) {
      await engine.files.move(mount, [...from, target.name], [...folder, target.name])
      moved.set(target.name, folder)
    }
    close()
  } catch (error) {
    refusal = error instanceof FileWriteError ? error.message : 'The engine could not do that.'
  } finally {
    moving = false
  }
}
</script>

<template>
  <c-modal
    :title
    :ui="{ content: 'w-[520px] max-w-[95vw]' }"
    @update:open="(open: boolean) => open || close()"
  >
    <template #body>
      <c-breadcrumb class="mb-2" :items="breadcrumbs" />
      <div class="border-default h-72 overflow-auto rounded-md border">
        <c-text
          v-if="listingQuery.isSuccess.value && folders.length === 0"
          class="text-muted block p-3"
          variant="body2"
        >
          No folders here.
        </c-text>
        <c-list>
          <c-list-item
            v-for="current in folders"
            :key="current.name"
            :disabled="isMoving(current.name)"
            @click="folder = [...folder, current.name]"
          >
            <c-icon class="shrink-0" :name="icons.folder" size="16" />
            <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ current.name }}</c-text>
            <c-icon class="shrink-0 opacity-60" :name="icons.chevronRight" size="16" />
          </c-list-item>
        </c-list>
      </div>
      <c-text v-if="refusal != null" class="text-error mt-2 block" variant="body2">
        {{ refusal }}
      </c-text>
    </template>
    <template #footer>
      <div class="flex w-full items-center gap-2">
        <c-button
          color="neutral"
          :icon="icons.folderNew"
          label="New Folder"
          variant="ghost"
          @click="createFolder"
        />
        <div class="flex-1" />
        <c-button color="neutral" label="Cancel" variant="ghost" @click="close()" />
        <c-button :disabled="blocked" label="Move Here" :loading="moving" @click="submit()" />
      </div>
    </template>
  </c-modal>
</template>
