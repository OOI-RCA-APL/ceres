<script lang="ts">
import type { FileEntry } from '@/api/files'

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
</script>

<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { computed } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { FileWriteError, isHiddenEntry, moveDestinationBlocked } from '@/api/files'
import { answer, useDialogs } from '@/dialogs'
import icons from '@/icons'

const { mount, mountLabel, from, targets, hidden } = defineProps<FileMoveDialogProps>()

/** Closes with the folder everything moved into, or `false` when anything stayed behind. */
const emit = defineEmits<{ close: [string[] | false] }>()

const engine = useEngine()
const dialogs = useDialogs()

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

/** Whether the folder named `name` here is one being moved, which nothing can move into. */
function isMoving(name: string) {
  return blocked || moveDestinationBlocked([...folder, name], from, targets)
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
    for (const target of targets) {
      await engine.files.move(mount, [...from, target.name], [...folder, target.name])
    }
    emit('close', folder)
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
    @update:open="(open: boolean) => open || emit('close', false)"
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
        <c-button color="neutral" label="Cancel" variant="ghost" @click="emit('close', false)" />
        <c-button :disabled="blocked" label="Move Here" :loading="moving" @click="submit()" />
      </div>
    </template>
  </c-modal>
</template>
