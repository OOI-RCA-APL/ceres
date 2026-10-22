<script lang="ts" setup>
import type { BreadcrumbItem, DropdownMenuItem } from '@nuxt/ui'
import { useQueryClient } from '@tanstack/vue-query'
import { useDropZone } from '@vueuse/core'
import multiDownload from 'multi-download'
import { computed, watch } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileAction,
  type FileEntry,
  type FileRoot,
  FileWriteError,
  droppedFiles,
  fileActions,
  filterEntries,
  formatFileSize,
  parseFilePath,
  previewOf,
} from '@/api/files'
import { type DialogHandle, useDialogs } from '@/dialogs'
import { Failure } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { clearOnOutsidePress, createRowSelection } from '@/row-selection'
import { utc } from '@/time'
import { afterMenuCloses, copyText } from '@/utilities'

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

// One setting per root, since a root full of dot entries worth seeing says nothing about another.
const persisted = usePersisted({
  schema: ({ object, boolean }) => object({ hidden: boolean().default(false) }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files', root] }]),
})

let filter = $ref('')

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

/** The open entry named as a member of its directory, which is what its actions act on. */
const openedEntry = $computed<FileEntry | null>(() =>
  entry == null || path.length === 0 ? null : { ...entry, name: path.at(-1) ?? '' },
)

const listingQuery = useQuery({
  queryKey: computed(() => ['files', 'list', root, persisted.hidden, ...path]),
  queryFn: () => engine.files.list(root, path, { hidden: persisted.hidden }),
  enabled: computed(() => entry?.kind === 'directory'),
  placeholderData: (previous) => previous,
})
const listing = $computed(() => listingQuery.data.value ?? null)
const entries = $computed(() => filterEntries(listing?.entries ?? [], filter))

// A name is unique within its directory, so it identifies the row.
const rows = createRowSelection({ ids: () => entries.map((current) => current.name) })
const selectedEntries = $computed(() => entries.filter((current) => rows.isSelected(current.name)))

watch(
  () => path,
  () => {
    filter = ''
    rows.clear()
  },
)

let list = $ref<HTMLElement | null>(null)
let toolbar = $ref<HTMLElement | null>(null)

// The toolbar's buttons act on the selection, so a press on one keeps it.
clearOnOutsidePress(
  () => list,
  () => rows.clear(),
  { ignore: [$$(toolbar)] },
)

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

/** What the browser shows under its breadcrumb, a failure to open winning over what it found. */
const view = $computed(() => (failureMessage == null ? (entry?.kind ?? 'loading') : 'failure'))

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

/** Whether two paths under the root name the same entry. A name never holds a slash, so the
joined forms compare exactly. */
function isSamePath(left: string[], right: string[]) {
  return left.join('/') === right.join('/')
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

/** Download each file among `targets`, entries of `directory`. A folder has no download. */
async function download(directory: string[], targets: FileEntry[]) {
  const files = targets.filter((target) => target.kind === 'file')
  await multiDownload(
    files.map((target) => engine.files.downloadUrl(root, [...directory, target.name])),
  )
}

/** Copy the path of each of `targets` under the root, one per line. */
async function copyPaths(directory: string[], targets: FileEntry[]) {
  await copyText(targets.map((target) => [...directory, target.name].join('/')).join('\n'))
  notify.success(targets.length > 1 ? 'Paths copied to clipboard.' : 'Path copied to clipboard.')
}

/** Ask where `targets`, entries of `directory`, go and move them there: one to a new path, several
into one folder. */
async function moveEntries(directory: string[], targets: FileEntry[]) {
  const [first] = targets
  if (first == null) {
    return
  }

  if (targets.length > 1) {
    await moveInto(directory, targets)
    return
  }

  const source = [...directory, first.name]
  const to = await answer(
    dialogs.fileName({
      title: 'Rename or Move',
      label: 'Path',
      value: source.join('/'),
      okLabel: 'Move',
    }),
  )
  const destination = to === false ? [] : parseFilePath(to)
  const moved =
    destination.length > 0 && (await write(() => engine.files.move(root, source, destination)))
  if (!moved) {
    return
  }

  if (isSamePath(source, path)) {
    path = destination
  } else if (isSamePath(destination.slice(0, -1), path)) {
    // A rename keeps the entry in view, so it stays the one selected.
    rows.replace([destination.at(-1) ?? ''])
  } else {
    rows.clear()
  }

  await refresh()
}

/** Ask for a folder and move each of `targets`, entries of `directory`, into it, stopping at the
first refusal. */
async function moveInto(directory: string[], targets: FileEntry[]) {
  const to = await answer(
    dialogs.fileName({
      title: `Move ${targets.length} Items`,
      label: 'Folder',
      value: directory.length === 0 ? '/' : directory.join('/'),
      okLabel: 'Move',
    }),
  )
  if (to === false) {
    return
  }

  const folder = parseFilePath(to)
  for (const target of targets) {
    const name = target.name
    if (!(await write(() => engine.files.move(root, [...directory, name], [...folder, name])))) {
      break
    }
  }

  rows.clear()
  await refresh()
}

function deleteMessage(targets: FileEntry[]) {
  const [first] = targets
  const folders = targets.some((target) => target.kind === 'directory')
  if (targets.length === 1 && first != null) {
    return folders ? `Delete "${first.name}" and everything in it?` : `Delete "${first.name}"?`
  }

  return folders
    ? `Delete ${targets.length} items and everything in the folders among them?`
    : `Delete ${targets.length} items?`
}

/** Confirm once, then delete each of `targets`, entries of `directory`, stopping at the first
refusal. Deleting the open entry opens its directory. */
async function deleteEntries(directory: string[], targets: FileEntry[]) {
  const [first] = targets
  if (first == null) {
    return
  }

  const confirmed = await answer(
    dialogs.delete({
      message: deleteMessage(targets),
      note: 'This cannot be undone.',
      confirmText: targets.length > 1 ? `${targets.length} items` : first.name,
    }),
  )
  if (!confirmed) {
    return
  }

  for (const target of targets) {
    const targetPath = [...directory, target.name]
    if (!(await write(() => engine.files.remove(root, targetPath)))) {
      break
    }

    if (isSamePath(targetPath, path)) {
      path = directory
    }
  }

  rows.clear()
  await refresh()
}

type FileActionView = {
  kind: FileAction
  label: string
  icon: string
  kbds?: string[]
  run: () => void
}

/** The keys the list answers, shown wherever the action they run is offered beside it. */
const actionKeys: Partial<Record<FileAction, string[]>> = {
  open: ['enter'],
  move: ['f2'],
  delete: ['backspace'],
}

/** How `kind` reads and what it does to `targets`, entries of `directory`. `keyed` shows the key
the list answers for it, which means nothing away from the list. */
function describeAction(
  kind: FileAction,
  directory: string[],
  targets: FileEntry[],
  keyed: boolean,
): FileActionView {
  const many = targets.length > 1
  const views: Record<FileAction, Omit<FileActionView, 'kind' | 'kbds'>> = {
    open: {
      label: 'Open',
      icon: icons.chevronRight,
      run: () => {
        const [first] = targets
        if (first != null) {
          path = [...directory, first.name]
        }
      },
    },
    download: {
      label: 'Download',
      icon: icons.download,
      run: () => void download(directory, targets),
    },
    copyPath: {
      label: many ? 'Copy Paths' : 'Copy Path',
      icon: icons.copy,
      run: () => void copyPaths(directory, targets),
    },
    move: {
      label: many ? 'Move' : 'Rename or Move',
      icon: many ? icons.move : icons.rename,
      run: () => void moveEntries(directory, targets),
    },
    delete: {
      label: 'Delete',
      icon: icons.delete,
      run: () => void deleteEntries(directory, targets),
    },
  }

  return { kind, kbds: keyed ? actionKeys[kind] : undefined, ...views[kind] }
}

/** The selection's actions, in the order a menu lists them, a separator between groups. */
const menuGroups: FileAction[][] = [['open'], ['download', 'copyPath', 'move'], ['delete']]

/** Actions that open a dialog, which waits for the menu that asked for it to finish closing. */
const asking: ReadonlySet<FileAction> = new Set(['move', 'delete'])

/** The menu every row's "…" button and a right click on any row open, acting on the selection. */
const menuItems = $computed<DropdownMenuItem[][]>(() => {
  const offered = fileActions(selectedEntries, writable)
  return menuGroups
    .map((group) =>
      group
        .filter((kind) => offered.includes(kind))
        .map((kind): DropdownMenuItem => {
          const action = describeAction(kind, path, selectedEntries, true)
          return {
            label: action.label,
            icon: action.icon,
            kbds: action.kbds,
            onSelect: () => (asking.has(kind) ? afterMenuCloses(action.run) : action.run()),
          }
        }),
    )
    .filter((group) => group.length > 0)
})

/** The actions ahead of the toolbar's own buttons: the selection's beside a directory's list, the
open entry's beside anything else. Opening has no button, and a file's download has its own. */
const toolbarActions = $computed<FileActionView[]>(() => {
  if (view === 'directory') {
    return fileActions(selectedEntries, writable)
      .filter((kind) => kind !== 'open')
      .map((kind) => describeAction(kind, path, selectedEntries, true))
  }

  if (openedEntry == null || (view !== 'file' && view !== 'other')) {
    return []
  }

  const targets = [openedEntry]
  return fileActions(targets, writable)
    .filter((kind) => kind !== 'open' && kind !== 'download')
    .map((kind) => describeAction(kind, path.slice(0, -1), targets, false))
})

/** Run `kind` on the selection when the selection offers it. */
function runOnSelection(kind: FileAction) {
  if (fileActions(selectedEntries, writable).includes(kind)) {
    describeAction(kind, path, selectedEntries, true).run()
  }
}

/** Scroll the row named `id` into view, the way a keyboard step lands on it. */
function reveal(id: string | null) {
  if (id != null) {
    list
      ?.querySelector(`[data-file-entry="${CSS.escape(id)}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }
}

// Every key the list answers stops here, so a workspace's own shortcuts never act on it too.
function onListKeydown(event: KeyboardEvent) {
  const command = event.metaKey || event.ctrlKey
  const plain = !command && !event.altKey
  if (command && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'a') {
    rows.replace(entries.map((current) => current.name))
  } else if (plain && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    reveal(rows.step(event.key === 'ArrowDown' ? 1 : -1, event.shiftKey ? 'extend' : 'replace'))
  } else if (plain && event.key === 'Escape' && rows.selected().length > 0) {
    rows.clear()
  } else if (plain && event.key === 'Enter' && event.target === list) {
    // Only the list itself, since a focused name or "…" button takes Enter as its own press.
    runOnSelection('open')
  } else if (plain && event.key === 'F2') {
    runOnSelection('move')
  } else if (plain && (event.key === 'Delete' || event.key === 'Backspace')) {
    runOnSelection('delete')
  } else {
    return
  }

  event.preventDefault()
  event.stopPropagation()
}

// A right click away from every row has nothing to act on, so it opens no menu.
function onListContext(event: MouseEvent) {
  if (!(event.target instanceof Element && event.target.closest('[data-file-entry]') != null)) {
    event.preventDefault()
  }
}

/** The row whose "…" menu opened last, the one dropdown holding the selection's items. The rest
hold none, so a change of selection updates one dropdown rather than one per row. */
let menuRow = $ref<string | null>(null)
const noMenuItems: DropdownMenuItem[][] = []

// A row's "…" menu acts on the selection, so opening it on a row outside one selects the row.
function onRowMenu(name: string, open: boolean) {
  if (open) {
    rows.ensureSelected(name)
    menuRow = name
  }
}
</script>

<template>
  <!-- The browser is its own size container, since a widget can be far narrower than the page. -->
  <div
    ref="dropZone"
    class="@container/files flex h-full min-h-0 flex-col gap-3"
    :class="writable && isOverDropZone && 'bg-elevated'"
  >
    <c-breadcrumb class="shrink-0" :items="breadcrumbs">
      <!-- Nuxt UI renders an item without `to` as a bare span, so a button inside it takes
      the focus, keyboard, and hover a link item has. Its click reaches the span's handler. -->
      <template #item="{ item, active, ui }">
        <component
          :is="item.to == null ? 'button' : 'span'"
          class="flex min-w-0 items-center gap-1.5"
          :class="
            item.to == null && [
              'outline-primary/25 rounded-md focus-visible:outline-3',
              !active && 'hover:text-default cursor-pointer transition-colors',
            ]
          "
          :disabled="item.to == null ? active : undefined"
          :type="item.to == null ? 'button' : undefined"
        >
          <c-icon v-if="item.icon" :class="ui.linkLeadingIcon({ active })" :name="item.icon" />
          <span :class="ui.linkLabel()">{{ item.label }}</span>
        </component>
      </template>
    </c-breadcrumb>

    <div ref="toolbar" class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
      <c-input
        v-if="view === 'directory'"
        v-model="filter"
        class="max-w-[440px] min-w-32 flex-1"
        :icon="icons.search"
        :loading="listingQuery.isFetching.value"
        placeholder="Filter"
        :spellcheck="false"
      >
        <template #trailing>
          <c-badge color="neutral" size="sm" variant="outline">{{ entries.length }}</c-badge>
        </template>
      </c-input>
      <template v-else-if="view === 'file' && entry != null">
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
      </template>
      <c-text v-else-if="view === 'failure'" class="text-muted" variant="body2">
        {{ failureMessage }}
      </c-text>
      <c-text v-else-if="view === 'other'" class="text-muted" variant="body2">
        This entry is neither a file nor a directory, so it cannot be opened here.
      </c-text>

      <div class="ml-auto flex shrink-0 items-center gap-1">
        <c-tooltip
          v-for="action in toolbarActions"
          :key="action.kind"
          :kbds="action.kbds"
          :text="action.label"
        >
          <c-button
            :aria-label="action.label"
            :color="action.kind === 'delete' ? 'error' : 'neutral'"
            :icon="action.icon"
            size="xs"
            variant="ghost"
            @click="action.run"
          />
        </c-tooltip>
        <template v-if="view === 'directory'">
          <!-- The icon shows whether hidden entries show, the tooltip what a press does. -->
          <c-tooltip :text="persisted.hidden ? 'Hide Hidden' : 'Show Hidden'">
            <c-button
              aria-label="Show Hidden"
              :aria-pressed="persisted.hidden"
              color="neutral"
              :icon="persisted.hidden ? icons.view : icons.hide"
              size="xs"
              variant="ghost"
              @click="persisted.hidden = !persisted.hidden"
            />
          </c-tooltip>
          <template v-if="writable">
            <input ref="fileInput" class="hidden" multiple type="file" @change="pickFiles" />
            <c-tooltip text="Upload">
              <c-button
                aria-label="Upload"
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
                aria-label="New Folder"
                color="neutral"
                :icon="icons.folderNew"
                size="xs"
                variant="ghost"
                @click="createDirectory"
              />
            </c-tooltip>
          </template>
        </template>
        <c-tooltip text="Refresh">
          <c-button
            aria-label="Refresh"
            color="neutral"
            :icon="icons.refresh"
            size="xs"
            variant="ghost"
            @click="refresh"
          />
        </c-tooltip>
      </div>
    </div>

    <!-- The content scrolls under the toolbar, which stays in view. -->
    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
      <template v-if="view === 'directory'">
        <c-text v-if="listing?.truncated" class="text-warning" variant="body2">
          Showing the first {{ listing.entries.length.toLocaleString() }} entries. The directory
          holds more than the engine lists at once.
        </c-text>
        <c-context-menu :items="menuItems">
          <div
            ref="list"
            class="outline-primary/25 rounded-md focus-visible:outline-3"
            tabindex="0"
            @contextmenu="onListContext"
            @keydown="onListKeydown"
          >
            <c-list>
              <c-list-item
                v-for="current in entries"
                :key="current.name"
                :data-file-entry="current.name"
                selectable
                :selected="rows.isSelected(current.name)"
                @click="rows.onClick(current.name, $event)"
                @contextmenu="rows.ensureSelected(current.name)"
              >
                <c-icon class="shrink-0" :name="entryIcon(current)" size="16" />
                <!-- Only the name opens the entry, the rest of the row selects it. -->
                <c-text class="min-w-0 flex-1 truncate" variant="body2">
                  <c-link
                    class="max-w-full cursor-pointer truncate text-left align-top hover:underline"
                    raw
                    tabindex="-1"
                    v-bind="opener([...path, current.name])"
                    @click.stop
                  >
                    {{ current.name }}
                  </c-link>
                </c-text>
                <!-- The name column wins as the browser narrows, the modified time going first. -->
                <c-text
                  class="text-muted hidden w-24 shrink-0 text-right @min-[360px]/files:block"
                  variant="body2"
                >
                  {{ formatFileSize(current.size) }}
                </c-text>
                <c-text
                  class="text-muted hidden w-44 shrink-0 text-right @min-[560px]/files:block"
                  variant="body2"
                >
                  {{ formatModified(current.modified) }}
                </c-text>
                <c-dropdown-menu
                  :items="menuRow === current.name ? menuItems : noMenuItems"
                  @update:open="(open: boolean) => onRowMenu(current.name, open)"
                >
                  <button
                    :aria-label="`More Actions for ${current.name}`"
                    class="flex shrink-0 items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
                    tabindex="-1"
                    type="button"
                    @click.stop
                    @mousedown.stop
                    @pointerdown.stop
                  >
                    <c-icon :name="icons.more" size="15" />
                  </button>
                </c-dropdown-menu>
              </c-list-item>
            </c-list>
          </div>
        </c-context-menu>
      </template>

      <template v-else-if="view === 'file' && entry != null">
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
            class="border-default min-h-0 overflow-auto rounded border p-3 text-sm"
            >{{ textQuery.data.value }}</pre>
        </template>
        <c-text v-else class="text-muted" variant="body2">
          This file is too large to preview. Download it to open it.
        </c-text>
      </template>
    </div>
  </div>
</template>
