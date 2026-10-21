<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { useQueryClient } from '@tanstack/vue-query'
import { useDropZone } from '@vueuse/core'
import { computed, watch } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileEntry,
  type FileRoot,
  FileWriteError,
  droppedFiles,
  filterEntries,
  formatFileSize,
  previewOf,
} from '@/api/files'
import { type DialogHandle, useDialogs } from '@/dialogs'
import { Failure } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { utc } from '@/time'

const {
  root,
  home = [],
  linkTo,
} = defineProps<{
  /** The ID of the root to browse. */
  root: string
  /** Breadcrumbs shown ahead of the root's own. */
  home?: BreadcrumbItem[]
  /** Where an entry at a path leads, which makes every entry a link. Without it, opening an entry
  only changes `path`. */
  linkTo?: (path: string[]) => string
}>()

/** The entry open under the root, the root itself when empty. */
let path = $(defineModel<string[]>('path', { required: true }))

const engine = useEngine()
const queryClient = useQueryClient()
const dialogs = useDialogs()
const notify = useNotify()

// One switch per root, since a root full of dot entries worth seeing says nothing about another.
const persisted = usePersisted({
  schema: ({ object, boolean }) => object({ hidden: boolean().default(false) }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files', root] }]),
})

let filter = $ref('')
watch(
  () => path,
  () => {
    filter = ''
  },
)

const rootsQuery = useQuery({
  queryKey: ['files', 'roots'],
  queryFn: () => engine.files.getRoots(),
})
const rootInfo = $computed(
  () => (rootsQuery.data.value ?? []).find((current: FileRoot) => current.id === root) ?? null,
)
const writable = $computed(() => rootInfo?.writable === true)

// A root is always a directory, so only a path under one needs asking what it is.
const statQuery = useQuery({
  queryKey: computed(() => ['files', 'stat', root, ...path]),
  queryFn: () => engine.files.stat(root, path),
  enabled: computed(() => path.length > 0),
})
const entry = $computed<FileEntry | null>(() =>
  path.length === 0
    ? { name: '', kind: 'directory', size: null, modified: null }
    : (statQuery.data.value ?? null),
)

const listingQuery = useQuery({
  queryKey: computed(() => ['files', 'list', root, persisted.hidden, ...path]),
  queryFn: () => engine.files.list(root, path, { hidden: persisted.hidden }),
  enabled: computed(() => entry?.kind === 'directory'),
  placeholderData: (previous) => previous,
})
const listing = $computed(() => listingQuery.data.value ?? null)
const entries = $computed(() => filterEntries(listing?.entries ?? [], filter))

const preview = $computed(() => (entry == null ? 'none' : previewOf(entry)))
const textQuery = useQuery({
  queryKey: computed(() => ['files', 'text', root, ...path]),
  queryFn: () => engine.files.readText(root, path, entry?.size ?? 0),
  enabled: computed(() => preview === 'text'),
})

const failure = $computed(() => statQuery.error.value ?? listingQuery.error.value)
const failureMessage = $computed(() => {
  if (failure instanceof Failure && failure.error.type === 'not-found-error') {
    return 'Nothing is here, or you cannot reach it.'
  }

  if (failure instanceof Failure && failure.error.type === 'not-permitted-error') {
    return 'You do not have access to this location.'
  }

  return failure == null ? null : 'The engine could not open this location.'
})

/** The props that open the entry at `target`, a link when `linkTo` is given. */
function opener(target: string[]) {
  return linkTo == null ? { onClick: () => (path = target) } : { to: linkTo(target) }
}

// A root missing from the listing is one this viewer cannot reach, whose ID means nothing to them.
const rootLabel = $computed(
  () => rootInfo?.label ?? (rootsQuery.isPending.value ? '' : 'Unavailable Root'),
)

const breadcrumbs = $computed<BreadcrumbItem[]>(() => [
  ...home,
  { label: rootLabel, ...opener([]) },
  ...path.map((name, index) => ({ label: name, ...opener(path.slice(0, index + 1)) })),
])

function entryIcon(current: FileEntry) {
  return { directory: icons.directory, file: icons.file, other: icons.fileOther }[current.kind]
}

function formatModified(modified: string | null) {
  return modified == null ? '' : utc(modified).format('YYYY-MM-DD HH:mm:ss')
}

// Invalidating refetches only the queries a browser has enabled, where `refetch` would also run
// the disabled ones, like reading a directory as text.
async function refresh() {
  await queryClient.invalidateQueries({ queryKey: ['files'] })
}

function answer<TPayload>(handle: DialogHandle<TPayload>): Promise<TPayload | false> {
  return new Promise((resolve) => handle.onOk(resolve).onCancel(() => resolve(false)))
}

/** Run `change`, reporting a refusal, and return whether it went through. */
async function write(change: () => Promise<void>): Promise<boolean> {
  try {
    await change()
    return true
  } catch (error) {
    notify.error(error instanceof FileWriteError ? error.message : 'The engine could not do that.')
    return false
  }
}

let fileInput = $ref<HTMLInputElement | null>(null)
let dropZone = $ref<HTMLElement | null>(null)
let isUploading = $ref(false)

const { isOverDropZone } = useDropZone($$(dropZone), {
  onDrop: (files, event) => {
    const dropped = droppedFiles(files ?? [], event.dataTransfer?.items ?? [])
    if (dropped.folders) {
      notify.error('Folders cannot be uploaded.')
    }

    void uploadFiles(dropped.files)
  },
})

/** Upload `files` into the open directory, asking before one replaces a file. */
async function uploadFiles(files: readonly File[]) {
  if (!writable || entry?.kind !== 'directory' || files.length === 0) {
    return
  }

  const directory = path
  isUploading = true
  try {
    for (const file of files) {
      const target = [...directory, file.name]
      const created = await engine.files.upload(root, target, file).then(
        () => true,
        (error: unknown) => error,
      )
      if (created instanceof FileWriteError && created.status === 412) {
        const replace = await answer(
          dialogs.confirm({ message: `Replace "${file.name}"?`, okLabel: 'Replace' }),
        )
        if (replace) {
          await write(() => engine.files.upload(root, target, file, { replace: true }))
        }
      } else if (created !== true) {
        await write(() => Promise.reject(created))
      }
    }
  } finally {
    isUploading = false
    await refresh()
  }
}

function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  void uploadFiles(files)
}

async function createDirectory() {
  const name = await answer(
    dialogs.fileName({ title: 'New Folder', label: 'Name', okLabel: 'Create' }),
  )
  if (name !== false && (await write(() => engine.files.createDirectory(root, [...path, name])))) {
    await refresh()
  }
}

async function moveEntry() {
  const source = path
  const to = await answer(
    dialogs.fileName({
      title: 'Rename or Move',
      label: 'Path',
      value: source.join('/'),
      okLabel: 'Move',
    }),
  )
  const destination = to === false ? [] : to.split('/').filter((name) => name !== '')
  if (destination.length > 0 && (await write(() => engine.files.move(root, source, destination)))) {
    await refresh()
    path = destination
  }
}

async function deleteEntry() {
  const target = path
  const name = target.at(-1) ?? ''
  const confirmed = await answer(
    dialogs.delete({
      message:
        entry?.kind === 'directory'
          ? `Delete "${name}" and everything in it?`
          : `Delete "${name}"?`,
      note: 'This cannot be undone.',
      confirmText: name,
    }),
  )
  if (confirmed && (await write(() => engine.files.remove(root, target)))) {
    await refresh()
    path = target.slice(0, -1)
  }
}
</script>

<template>
  <div
    ref="dropZone"
    class="flex min-h-full flex-col gap-3"
    :class="writable && isOverDropZone && 'bg-elevated'"
  >
    <div class="flex items-center gap-1">
      <c-breadcrumb class="min-w-0 flex-1" :items="breadcrumbs" />
      <c-switch v-model="persisted.hidden" class="mr-2" label="Show hidden" />
      <template v-if="writable && entry?.kind === 'directory'">
        <input ref="fileInput" class="hidden" multiple type="file" @change="pickFiles" />
        <c-tooltip text="Upload">
          <c-button
            color="neutral"
            :icon="icons.upload"
            :loading="isUploading"
            size="xs"
            variant="ghost"
            @click="fileInput?.click()"
          />
        </c-tooltip>
        <c-tooltip text="New Folder">
          <c-button
            color="neutral"
            :icon="icons.folderNew"
            size="xs"
            variant="ghost"
            @click="createDirectory"
          />
        </c-tooltip>
      </template>
      <template v-if="writable && path.length > 0 && entry != null">
        <c-tooltip text="Rename or Move">
          <c-button
            color="neutral"
            :icon="icons.rename"
            size="xs"
            variant="ghost"
            @click="moveEntry"
          />
        </c-tooltip>
        <c-tooltip text="Delete">
          <c-button
            color="error"
            :icon="icons.delete"
            size="xs"
            variant="ghost"
            @click="deleteEntry"
          />
        </c-tooltip>
      </template>
      <c-tooltip text="Refresh">
        <c-button
          color="neutral"
          :icon="icons.refresh"
          size="xs"
          variant="ghost"
          @click="refresh"
        />
      </c-tooltip>
    </div>

    <c-text v-if="failureMessage != null" class="text-muted" variant="body2">{{
      failureMessage
    }}</c-text>

    <template v-else-if="entry?.kind === 'directory'">
      <c-input
        v-model="filter"
        class="w-full max-w-[440px]"
        :icon="icons.search"
        :loading="listingQuery.isFetching.value"
        placeholder="Filter"
        :spellcheck="false"
      >
        <template #trailing>
          <c-badge color="neutral" size="sm" variant="outline">{{ entries.length }}</c-badge>
        </template>
      </c-input>
      <c-text v-if="listing?.truncated" class="text-warning" variant="body2">
        Showing the first {{ listing.entries.length.toLocaleString() }} entries. The directory holds
        more than the engine lists at once.
      </c-text>
      <c-list>
        <c-list-item
          v-for="current in entries"
          :key="current.name"
          v-bind="opener([...path, current.name])"
        >
          <c-icon class="shrink-0" :name="entryIcon(current)" size="16" />
          <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ current.name }}</c-text>
          <c-text class="text-muted w-24 shrink-0 text-right" variant="body2">
            {{ formatFileSize(current.size) }}
          </c-text>
          <c-text class="text-muted w-44 shrink-0 text-right" variant="body2">
            {{ formatModified(current.modified) }}
          </c-text>
        </c-list-item>
      </c-list>
    </template>

    <template v-else-if="entry?.kind === 'file'">
      <div class="flex items-center gap-3">
        <c-text class="text-muted" variant="body2">
          {{ formatFileSize(entry.size) }} &middot; {{ formatModified(entry.modified) }}
        </c-text>
        <c-button
          color="neutral"
          external
          :href="engine.files.downloadUrl(root, path)"
          :icon="icons.download"
          label="Download"
          size="sm"
          variant="outline"
        />
      </div>
      <img
        v-if="preview === 'image'"
        :alt="entry.name"
        class="max-w-full self-start"
        :src="engine.files.sourceUrl(root, path)"
      />
      <video
        v-else-if="preview === 'video'"
        class="max-w-full self-start"
        controls
        :src="engine.files.sourceUrl(root, path)"
      />
      <audio
        v-else-if="preview === 'audio'"
        class="w-full max-w-[640px]"
        controls
        :src="engine.files.sourceUrl(root, path)"
      />
      <template v-else-if="preview === 'text'">
        <c-text v-if="textQuery.data.value === null" class="text-muted" variant="body2">
          This file is binary. Download it to open it.
        </c-text>
        <pre
          v-else-if="textQuery.data.value != null"
          class="border-default overflow-auto rounded border p-3 text-sm"
          >{{ textQuery.data.value }}</pre>
      </template>
      <c-text v-else class="text-muted" variant="body2">
        This file is too large to preview. Download it to open it.
      </c-text>
    </template>

    <c-text v-else-if="entry?.kind === 'other'" class="text-muted" variant="body2">
      This entry is neither a file nor a directory, so it cannot be opened here.
    </c-text>
  </div>
</template>
