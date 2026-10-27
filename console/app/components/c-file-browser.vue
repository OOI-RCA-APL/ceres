<script lang="ts" setup>
import type { BreadcrumbItem, ContextMenuItem } from '@nuxt/ui'
import { useQueryClient } from '@tanstack/vue-query'
import { useDropZone, useElementSize } from '@vueuse/core'
import { computed, watch } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  FILE_ENTRY_BUTTONS,
  type FileAction,
  type FileActionView,
  type FileColumn,
  FileColumnsModel,
  FileCopyError,
  type FileEntry,
  type FilePlace,
  type FilePreviewMode,
  type FileStat,
  FilePreviewSettingsModel,
  FileWriteError,
  LISTING_MIN_WIDTH,
  PREVIEW_MIN_WIDTH,
  copyFile,
  droppedFiles,
  fileActions,
  fileColumns,
  fileInfoPlace,
  filesDownloadPath,
  filesPagePath,
  findFileMount,
  filePlace,
  filterEntries,
  formatFileSize,
  formatFileTime,
  fileNameStemEnd,
  fileStatQueryKey,
  fileTextQueryKey,
  isHiddenEntry,
  previewMode,
  previewTarget,
  selectionSummary,
} from '@/api/files'
import { FILE_BREADCRUMB_UI } from '@/components/c-file-history.vue'
import { answer, useDialogs } from '@/dialogs'
import { Failure } from '@/errors'
import type { ValueHistory } from '@/history'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { clearOnOutsidePress, createRowSelection } from '@/row-selection'
import { afterMenuCloses, copyText, downloadFrom, openContextMenu } from '@/utilities'

const {
  mount,
  history,
  viewKey,
  home = [],
  linkTo,
} = defineProps<{
  /** The ID of the mount to browse. */
  mount: string
  /** Names the view showing the browser, `page` or `widget/<id>`, whose preview layout it keeps. */
  viewKey: string
  /** The caller's Back and Forward, which records each place it opens. The browser replaces the
  current place for a step that stands in place, a preview or a rename. */
  history: ValueHistory<FilePlace>
  /** Breadcrumbs shown ahead of the mount's own. */
  home?: BreadcrumbItem[]
  /** Where an entry at a path leads, which makes every entry a link. Without it, opening an entry
  only changes `path`. */
  linkTo?: (path: string[]) => string
}>()

/** The entry open under the mount, the mount itself when empty. A file previewed beside the
listing is open too, under its directory. */
let path = $(defineModel<string[]>('path', { required: true }))

const emit = defineEmits<{
  /** The selection asks a side preview to show `path`, which a caller keeping `path` in its URL
  replaces there rather than pushing, since a step through files is not a place to go back to. */
  preview: [path: string[]]
  /** Back or Forward picked `place`, which the caller opens. */
  go: [place: FilePlace]
}>()

/** Show `target` beside the listing without making it a place to go back to. */
function previewInPlace(target: string[]) {
  history.replace(filePlace(mount, target))
  emit('preview', target)
}

/** Open `target` in place of the current entry, which Back then skips. */
function openInPlace(target: string[]) {
  history.replace(filePlace(mount, target))
  path = target
}

const engine = useEngine()
const queryClient = useQueryClient()
const dialogs = useDialogs()
const notify = useNotify()
const navigation = useNavigation()

// One setting per mount, since a mount full of dot entries worth seeing says nothing about another.
const persisted = usePersisted({
  schema: ({ object, boolean }) => object({ hidden: boolean().default(false) }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files', mount] }]),
})

const columns = usePersisted({
  schema: FileColumnsModel,
  methods: [{ type: 'local-storage', key: ['files', 'columns'] }],
})

// One per file view, since a narrow widget and a wide page want their panels sized apart.
const previewSettings = usePersisted({
  schema: FilePreviewSettingsModel,
  methods: computed(() => [
    { type: 'local-storage' as const, key: ['files', 'preview', ...viewKey.split('/')] },
  ]),
})

let root = $ref<HTMLElement | null>(null)
const { width: rootWidth } = useElementSize($$(root))

/** Where a file opens, the persisted choice unless the browser is too narrow for a side panel. */
const mode = $computed(() => previewMode(previewSettings.mode, rootWidth.value))
const wide = $computed(() => previewMode('side', rootWidth.value) === 'side')

const previewChoices: { mode: FilePreviewMode; label: string; icon: string }[] = [
  { mode: 'side', label: 'Preview Beside', icon: icons.previewSide },
  { mode: 'full', label: 'Preview Full', icon: icons.previewFull },
]

// Measured from the browser rather than the window, since a widget hosts it too.
const panelMax = $computed(() => Math.max(PREVIEW_MIN_WIDTH, rootWidth.value - LISTING_MIN_WIDTH))
const panelWidth = $computed(() =>
  Math.min(Math.max(previewSettings.width, PREVIEW_MIN_WIDTH), panelMax),
)

// The handle grows what lies before it, so it sizes the listing and the panel takes the rest.
const listingWidth = $computed({
  get: () => Math.max(0, rootWidth.value - panelWidth),
  set: (value: number) => (previewSettings.width = rootWidth.value - value),
})

// The name column wins as the browser narrows, Created going first, then Modified, then Size.
const columnClasses: Record<FileColumn, string> = {
  size: 'w-24 @min-[360px]/files:block',
  modified: 'w-44 @min-[560px]/files:block',
  created: 'w-44 @min-[760px]/files:block',
}

const shownColumns = $computed(() => fileColumns.filter(({ column }) => columns[column]))

function cellText(current: FileEntry, column: FileColumn) {
  return column === 'size' ? formatFileSize(current.size) : formatFileTime(current[column])
}

/** The header's menu, one checkbox per optional column. */
const columnItems = $computed<ContextMenuItem[]>(() =>
  fileColumns.map(({ column, label }) => ({
    label,
    type: 'checkbox',
    checked: columns[column],
    onUpdateChecked: (checked: boolean) => (columns[column] = checked),
  })),
)

let filter = $ref('')

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})
const mountInfo = $computed(() => findFileMount(mountsQuery.data.value, mount))
const writable = $computed(() => mountInfo?.access === 'edit')

// A mount is always a directory, so only a path under one needs asking what it is.
const statQuery = useQuery(
  computed(() => ({ ...statQueryOptions(path), enabled: path.length > 0 })),
)
const entry = $computed<FileEntry | null>(() =>
  path.length === 0
    ? { name: '', kind: 'directory', size: null, modified: null, created: null }
    : (statQuery.data.value ?? listedEntry(path)),
)

/** The open entry named as a member of its directory, which is what its actions act on. */
const openedEntry = $computed<FileEntry | null>(() =>
  entry == null || path.length === 0 ? null : { ...entry, name: path.at(-1) ?? '' },
)

/** Whether a listing shows, the open directory's or, beside a side preview, the open file's. */
const listed = $computed(() => entry != null && (entry.kind === 'directory' || mode === 'side'))

/** The directory the browser lists, or holding the open file. */
const currentDirectory = $computed(() =>
  entry == null || entry.kind === 'directory' ? path : path.slice(0, -1),
)

const listingQuery = useQuery({
  queryKey: computed(() => ['files', 'list', mount, ...currentDirectory]),
  queryFn: () => engine.files.list(mount, currentDirectory),
  enabled: $$(listed),
  placeholderData: (previous) => previous,
})
const listing = $computed(() => listingQuery.data.value ?? null)

/** What the listing on screen says of `target`, so a step within it shows before the engine
answers. The listing may still be the previous directory's. */
function listedEntry(target: string[]): FileEntry | null {
  if (listing == null) {
    return null
  }

  if (isSamePath(target, listing.directory)) {
    return {
      name: target.at(-1) ?? '',
      kind: 'directory',
      size: null,
      modified: null,
      created: null,
    }
  }

  const name = target.at(-1)
  return isSamePath(target.slice(0, -1), listing.directory)
    ? (listing.entries.find((current) => current.name === name) ?? null)
    : null
}
const visibleEntries = $computed(() =>
  (listing?.entries ?? []).filter((current) => persisted.hidden || !isHiddenEntry(current)),
)
const hiddenCount = $computed(() => (listing?.entries.length ?? 0) - visibleEntries.length)
const entries = $computed(() => filterEntries(visibleEntries, filter))

/** What stands in for a loaded listing that shows nothing, a filter's answer winning. */
const emptyTitle = $computed(() => {
  if (listing == null || entries.length > 0) {
    return null
  }

  if (filter.trim() !== '') {
    return 'No Matches'
  }

  return hiddenCount > 0 ? 'No Visible Files' : 'Empty Directory'
})

// A name is unique within its directory, so it identifies the row.
const rows = createRowSelection({ ids: () => entries.map((current) => current.name) })
const selectedEntries = $computed(() => entries.filter((current) => rows.isSelected(current.name)))

watch(
  () => currentDirectory.join('/'),
  () => {
    filter = ''
    rows.clear()
  },
)

/** The file a side preview shows from the URL, which its row shows selected. */
const openedFileName = $computed(() =>
  listed && entry != null && entry.kind !== 'directory' ? (path.at(-1) ?? null) : null,
)

// Declared after the watch that clears the rows, so a file opened in another directory stays
// selected once both run.
watch(
  $$(openedFileName),
  (name) => {
    if (name != null && !(rows.selected().length === 1 && rows.isSelected(name))) {
      rows.replace([name])
    }
  },
  { immediate: true },
)

// Selecting one entry asks for its description, so a copy of its system path has the text in hand
// inside the click, where Safari and plain HTTP require it. Selecting one file previews it, and
// anything else returns the URL to the directory.
watch(
  () => selectedEntries.map((current) => current.name).join('/'),
  () => {
    const [only, ...rest] = selectedEntries
    if (only != null && rest.length === 0 && mountInfo?.reveal_paths === true) {
      void queryClient.prefetchQuery(statQueryOptions([...currentDirectory, only.name]))
    }

    if (mode !== 'side' || !listed) {
      return
    }

    const target = previewTarget(currentDirectory, selectedEntries)
    if (!isSamePath(target, path)) {
      previewInPlace(target)
    }
  },
)

/** What the side panel shows, the open file or else the one entry selected. */
const panelTarget = $computed(() => {
  if (openedEntry != null && openedFileName != null) {
    return { path, entry: openedEntry }
  }

  const [only] = selectedEntries
  return selectedEntries.length === 1 && only != null
    ? { path: [...currentDirectory, only.name], entry: only }
    : null
})

let list = $ref<HTMLElement | null>(null)
let toolbar = $ref<HTMLElement | null>(null)

// A press in the toolbar keeps the selection, as in Finder.
clearOnOutsidePress(
  () => list,
  () => rows.clear(),
  { ignore: [$$(toolbar)] },
)

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

/** What the browser shows under its breadcrumb, a failure to open winning over what it found. A
listing shows for a directory, and beside a side preview for anything else. */
const view = $computed(() => {
  if (failureMessage != null) {
    return 'failure'
  }

  if (entry == null) {
    return 'loading'
  }

  return listed ? 'listing' : entry.kind
})

/** Whether the panel shows beside the listing. */
const side = $computed(() => view === 'listing' && mode === 'side')

/** The props that open the entry at `target`, a link when `linkTo` is given. */
function opener(target: string[]) {
  return linkTo == null ? { onClick: () => (path = target) } : { to: linkTo(target) }
}

// A mount missing from the listing is one this viewer cannot reach, whose ID means nothing to them.
const mountLabel = $computed(
  () => mountInfo?.label ?? (mountsQuery.isPending.value ? '' : 'Unavailable Mount'),
)

/** A crumb for a place in the mount, whose menu describes it and copies its link. The current
place's crumb opens that menu on a click, since going to it would change nothing. */
function placeCrumb(target: string[], crumb: BreadcrumbItem): BreadcrumbItem {
  const current = target.length === path.length
  return { ...crumb, place: target, ...(current ? {} : opener(target)) }
}

const breadcrumbs = $computed<BreadcrumbItem[]>(() => [
  ...home,
  placeCrumb([], {
    label: mountLabel,
    icon: icons.mount,
    viewOnly: mountInfo != null && !writable,
  }),
  ...path.map((name, index) => placeCrumb(path.slice(0, index + 1), { label: name })),
])

/** The menu of the crumb for `target`. A folder in a writable mount takes a new folder too. */
function crumbMenu(target: string[]): ContextMenuItem[][] {
  const folder = target.length < path.length || view === 'listing'
  return [
    [
      {
        label: 'Info',
        icon: icons.details,
        onSelect: () => afterMenuCloses(() => showInfo(target)),
      },
      { label: 'Copy Link', icon: icons.share, onSelect: () => void copyLinks([target]) },
    ],
    writable && folder
      ? [
          {
            label: 'New Folder',
            icon: icons.folderNew,
            onSelect: () => afterMenuCloses(() => void createDirectory(target)),
          },
        ]
      : [],
  ].filter((group) => group.length > 0)
}

function entryIcon(current: FileEntry) {
  return { directory: icons.folder, file: icons.file, other: icons.fileOther }[current.kind]
}

// Invalidating refetches only the queries a browser has enabled, where `refetch` would also run
// the disabled ones, like reading a directory as text.
async function refresh() {
  await queryClient.invalidateQueries({ queryKey: ['files'] })
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

/** Whether two paths under the mount name the same entry. A name never holds a slash, so the
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
  if (!writable || !listed || files.length === 0) {
    return
  }

  const directory = currentDirectory
  isUploading = true
  try {
    for (const file of files) {
      const target = [...directory, file.name]
      const created = await engine.files.upload(mount, target, file).then(
        () => true,
        (error: unknown) => error,
      )
      if (created instanceof FileWriteError && created.status === 412) {
        const replace = await answer(
          dialogs.confirm({ message: `Replace "${file.name}"?`, okLabel: 'Replace' }),
        )
        if (replace) {
          await write(() => engine.files.upload(mount, target, file, { replace: true }))
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

/** Ask for a name and create a folder by it in `directory`. */
async function createDirectory(directory: string[]) {
  const name = await answer(
    dialogs.fileName({ title: 'New Folder', label: 'Name', okLabel: 'Create' }),
  )
  const target = name === false ? null : [...directory, name]
  if (target != null && (await write(() => engine.files.createDirectory(mount, target)))) {
    await refresh()
  }
}

/** Download `targets`, entries of `directory`, one file or folder as itself and several as one zip
of `directory` holding them. A folder's zip keeps dot names while the listing shows them. */
function download(directory: string[], targets: FileEntry[]) {
  const names = targets.filter((target) => target.kind !== 'other').map((target) => target.name)
  const [only, ...rest] = names
  if (only == null) {
    return
  }

  const hidden = persisted.hidden
  downloadFrom(
    rest.length === 0
      ? filesDownloadPath(mount, [...directory, only], { hidden })
      : filesDownloadPath(mount, directory, { entries: names, hidden }),
  )
}

/** What the browser offers for `targets`. */
function actionsFor(targets: readonly FileEntry[]) {
  return fileActions(targets, writable, mountInfo?.reveal_paths ?? false)
}

function statQueryOptions(target: string[]) {
  return {
    queryKey: fileStatQueryKey(mount, target),
    queryFn: () => engine.files.stat(mount, target),
  }
}

/** Copy where `target` lives on the server. */
async function copySystemPath(target: string[]) {
  const failure = 'Could not copy the path, open Info and copy it there.'
  const stat =
    queryClient.getQueryData<FileStat>(fileStatQueryKey(mount, target)) ??
    (await queryClient.fetchQuery(statQueryOptions(target)).catch(() => null))
  if (stat?.path == null) {
    notify.error(failure)
    return
  }

  try {
    await copyText(stat.path)
    notify.success('Path copied to clipboard.')
  } catch {
    notify.error(failure)
  }
}

/** The text preview of the file at `target` when a preview already read it. */
function cachedText(target: string[]): string | null {
  return queryClient.getQueryData<string | null>(fileTextQueryKey(mount, target)) ?? null
}

/** Copy the contents of the file `entry` at `target`, from a cached text preview when there is
one. Call it inside the gesture that asked, before any `await`. */
function copyContents(target: string[], entry: FileEntry) {
  const text = cachedText(target)
  const copied =
    text == null ? copyFile(entry, () => engine.files.readBlob(mount, target)) : copyText(text)
  copied.then(
    () => notify.success('Copied to clipboard.'),
    (error: unknown) =>
      notify.error(error instanceof FileCopyError ? error.message : 'Could not copy the file.'),
  )
}

/** Copy a link to the files page at each of `targets`, one per line. The eye and the selection
stay out of it. */
async function copyLinks(targets: string[][]) {
  try {
    await copyText(
      targets.map((target) => navigation.link({ path: filesPagePath(mount, target) })).join('\n'),
    )
    notify.success(targets.length > 1 ? 'Links copied to clipboard.' : 'Link copied to clipboard.')
  } catch {
    notify.error('Could not copy the link.')
  }
}

/** Ask for a new name for `target`, an entry of `directory`, and give it that name. */
async function renameEntry(directory: string[], target: FileEntry) {
  const name = await answer(
    dialogs.fileName({
      title: 'Rename',
      label: 'Name',
      value: target.name,
      selectionEnd: fileNameStemEnd(target.name, target.kind),
      okLabel: 'Rename',
    }),
  )
  if (name === false) {
    return
  }

  const source = [...directory, target.name]
  const destination = [...directory, name]
  if (!(await write(() => engine.files.move(mount, source, destination)))) {
    return
  }

  // A renamed preview stays in place beside the listing, so its new URL replaces the old one.
  if (isSamePath(source, path)) {
    if (side) {
      previewInPlace(destination)
    } else {
      openInPlace(destination)
    }
  }

  rows.replace([name])
  await refresh()
}

/** Ask for a folder and move or copy `targets`, entries of `directory`, into it. The dialog writes
them, so the listing refreshes after it closes whatever landed. */
async function placeEntries(directory: string[], targets: FileEntry[], mode: 'move' | 'copy') {
  const placed = await answer(
    dialogs.placeFiles({
      mount,
      mountLabel,
      from: directory,
      targets,
      hidden: persisted.hidden,
      mode,
    }),
  )

  // The open entry follows wherever it moved, even when a refusal kept others behind.
  const opened = isSamePath(directory, path.slice(0, -1)) ? path.at(-1) : undefined
  const folder =
    mode === 'copy' || placed === false || opened == null ? undefined : placed.get(opened)
  if (opened != null && folder != null) {
    path = [...folder, opened]
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
    if (!(await write(() => engine.files.remove(mount, targetPath)))) {
      break
    }

    // Beside a listing the deleted file only stood in the URL as a preview, which Back must not
    // return to.
    if (isSamePath(targetPath, path)) {
      if (side) {
        previewInPlace(directory)
      } else {
        openInPlace(directory)
      }
    }
  }

  rows.clear()
  await refresh()
}

/** Describe the entry at `target`, the mount itself when empty. */
function showInfo(target: string[]) {
  dialogs.fileInfo({
    mount,
    path: target,
    ...fileInfoPlace(mountInfo, mountLabel, target),
    writable,
  })
}

/** The keys the list answers, shown wherever the action they run is offered beside it. Delete shows
the key each platform's keyboard labels delete, Backspace on a Mac. */
const actionKeys: Partial<Record<FileAction, string[]>> = {
  open: ['enter'],
  copy: ['meta', 'c'],
  rename: ['f2'],
  delete: [useKbd().macOS.value ? 'backspace' : 'delete'],
}

/** How `kind` reads and what it does to `targets`, entries of `directory`. `keyed` shows the key
the list answers for it, which means nothing away from the list. */
function describeAction(
  kind: FileAction,
  directory: string[],
  targets: FileEntry[],
  keyed: boolean,
): FileActionView {
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
    viewRaw: {
      label: 'View Raw',
      icon: icons.open,
      run: () => {
        const [first] = targets
        if (first != null) {
          window.open(
            engine.files.sourceUrl(mount, [...directory, first.name]),
            '_blank',
            'noopener',
          )
        }
      },
    },
    info: {
      label: 'Info',
      icon: icons.details,
      run: () => showInfo([...directory, ...targets.slice(0, 1).map((first) => first.name)]),
    },
    download: {
      label: 'Download',
      icon: icons.download,
      run: () => void download(directory, targets),
    },
    copy: {
      label: 'Copy',
      icon: icons.copy,
      // Outside a secure context only text already in hand reaches the clipboard.
      ...(!window.isSecureContext &&
      targets.every((target) => cachedText([...directory, target.name]) == null)
        ? { disabled: true, description: 'Needs HTTPS' }
        : {}),
      run: () => {
        const [first] = targets
        if (first != null) {
          copyContents([...directory, first.name], first)
        }
      },
    },
    copyPath: {
      label: 'Copy System Path',
      icon: icons.path,
      run: () => {
        const [first] = targets
        if (first != null) {
          void copySystemPath([...directory, first.name])
        }
      },
    },
    copyLink: {
      label: 'Copy Link',
      icon: icons.share,
      run: () => void copyLinks(targets.map((target) => [...directory, target.name])),
    },
    rename: {
      label: 'Rename',
      icon: icons.rename,
      run: () => {
        const [first] = targets
        if (first != null) {
          void renameEntry(directory, first)
        }
      },
    },
    move: {
      label: 'Move',
      icon: icons.move,
      run: () => void placeEntries(directory, targets, 'move'),
    },
    copyTo: {
      label: 'Copy To',
      icon: icons.duplicate,
      run: () => void placeEntries(directory, targets, 'copy'),
    },
    delete: {
      label: 'Delete',
      icon: icons.delete,
      run: () => void deleteEntries(directory, targets),
    },
  }

  return { kind, kbds: keyed ? actionKeys[kind] : undefined, ...views[kind] }
}

/** The menu's entries in order, a separator between groups. Select All rides along so its key shows
in a menu too. */
const menuGroups: (FileAction | 'selectAll')[][] = [
  ['open', 'viewRaw', 'info'],
  ['download', 'copy', 'copyPath', 'copyLink', 'rename', 'move', 'copyTo'],
  ['selectAll'],
  ['delete'],
]

/** Actions that open a dialog, which waits for the menu that asked for it to finish closing. */
const asking: ReadonlySet<FileAction> = new Set(['info', 'rename', 'move', 'copyTo', 'delete'])

function selectAll() {
  rows.replace(entries.map((current) => current.name))
}

/** The menu every row's "…" button and a right click on any row open, acting on the selection. */
const menuItems = $computed<ContextMenuItem[][]>(() => {
  const offered = actionsFor(selectedEntries)
  return menuGroups
    .map((group) =>
      group
        .filter((kind) => kind === 'selectAll' || offered.includes(kind))
        .map((kind): ContextMenuItem => {
          if (kind === 'selectAll') {
            const everything = selectedEntries.length === entries.length
            return {
              label: 'Select All',
              icon: icons.selectAll,
              kbds: ['meta', 'a'],
              disabled: everything,
              onSelect: selectAll,
            }
          }

          return menuItem(describeAction(kind, currentDirectory, selectedEntries, true))
        }),
    )
    .filter((group) => group.length > 0)
})

function menuItem(action: FileActionView): ContextMenuItem {
  return {
    label: action.label,
    icon: action.icon,
    kbds: action.kbds,
    disabled: action.disabled,
    description: action.description,
    onSelect: () => (asking.has(action.kind) ? afterMenuCloses(action.run) : action.run()),
  }
}

/** What the entry at `target` offers shown alone, open or previewed beside the listing: the same
buttons either way, then a menu with the rest. Opening has no place, since it is open or has its
own button. */
function entryActions(target: string[], shown: FileEntry) {
  const directory = target.slice(0, -1)
  const offered: FileAction[] = actionsFor([shown]).filter((kind) => kind !== 'open')
  const describe = (kind: FileAction) => describeAction(kind, directory, [shown], false)
  return {
    buttons: FILE_ENTRY_BUTTONS.filter((kind) => offered.includes(kind)).map(describe),
    more: menuGroups
      .map((group) =>
        group
          .filter(
            (kind): kind is FileAction =>
              kind !== 'selectAll' && offered.includes(kind) && !FILE_ENTRY_BUTTONS.includes(kind),
          )
          .map((kind) => menuItem(describe(kind))),
      )
      .filter((group) => group.length > 0),
  }
}

const openedActions = $computed(() =>
  openedEntry != null && (view === 'file' || view === 'other')
    ? entryActions(path, openedEntry)
    : null,
)

const panelActions = $computed(() =>
  panelTarget == null ? null : entryActions(panelTarget.path, panelTarget.entry),
)

/** Run `kind` on the selection when the selection offers it. */
function runOnSelection(kind: FileAction) {
  if (actionsFor(selectedEntries).includes(kind)) {
    describeAction(kind, currentDirectory, selectedEntries, true).run()
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
    selectAll()
  } else if (plain && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    reveal(rows.step(event.key === 'ArrowDown' ? 1 : -1, event.shiftKey ? 'extend' : 'replace'))
  } else if (plain && event.key === 'Escape' && rows.selected().length > 0) {
    rows.clear()
  } else if (plain && event.key === 'Enter' && event.target === list) {
    // Only the list itself, since a focused name or "…" button takes Enter as its own press.
    runOnSelection('open')
  } else if (plain && event.key === 'F2') {
    runOnSelection('rename')
  } else if (plain && (event.key === 'Delete' || event.key === 'Backspace')) {
    runOnSelection('delete')
  } else {
    return
  }

  event.preventDefault()
  event.stopPropagation()
}

// The copy key copies one selected file's contents. Highlighted text copies itself, as it does
// past the workspace's own handler, which this one keeps from copying the widget too.
function onListCopy(event: ClipboardEvent) {
  const [only] = selectedEntries
  if (
    only == null ||
    !actionsFor(selectedEntries).includes('copy') ||
    window.getSelection()?.isCollapsed === false
  ) {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  const target = [...currentDirectory, only.name]
  const text = cachedText(target)
  if (text != null && event.clipboardData != null) {
    event.clipboardData.setData('text/plain', text)
    notify.success('Copied to clipboard.')
  } else if (!window.isSecureContext) {
    notify.error('Copying a file needs HTTPS.')
  } else {
    copyContents(target, only)
  }
}

// A right click away from every row has nothing to act on, so it opens no menu.
function onListContext(event: MouseEvent) {
  if (!(event.target instanceof Element && event.target.closest('[data-file-entry]') != null)) {
    event.preventDefault()
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
    <div class="flex shrink-0 items-center gap-2">
      <c-file-history :history @go="emit('go', $event)" />
      <c-breadcrumb class="min-w-0" :items="breadcrumbs" :ui="FILE_BREADCRUMB_UI">
        <!-- Nuxt UI renders an item without `to` as a bare span, so a button inside it takes
        the focus, keyboard, and hover a link item has. Its click reaches the span's handler. -->
        <template #item="{ item, active, ui }">
          <!-- The trigger binds to one element, and the dropdown menu renders several. -->
          <c-context-menu :disabled="item.place == null" :items="crumbMenu(item.place ?? [])">
            <span class="flex min-w-0">
              <c-dropdown-menu
                :disabled="item.place == null || item.to != null || item.onClick != null"
                :items="crumbMenu(item.place ?? [])"
              >
                <component
                  :is="item.to == null ? 'button' : 'span'"
                  class="flex min-w-0 items-center gap-1.5"
                  :class="
                    item.to == null && [
                      'outline-primary/25 rounded-md focus-visible:outline-3',
                      (!active || item.place != null) &&
                        'hover:text-default cursor-pointer transition-colors',
                    ]
                  "
                  :disabled="item.to == null ? active && item.place == null : undefined"
                  :type="item.to == null ? 'button' : undefined"
                >
                  <c-icon
                    v-if="item.icon"
                    :class="ui.linkLeadingIcon({ active })"
                    :name="item.icon"
                  />
                  <span :class="ui.linkLabel()">{{ item.label }}</span>
                  <c-file-read-only-lock v-if="item.viewOnly" />
                </component>
              </c-dropdown-menu>
            </span>
          </c-context-menu>
        </template>
      </c-breadcrumb>
    </div>

    <!-- Over the listing alone while a side preview shows, since its buttons act on the
    listing. -->
    <div
      ref="toolbar"
      class="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1"
      :style="side ? { width: `${listingWidth}px` } : undefined"
    >
      <c-input
        v-if="view === 'listing'"
        v-model="filter"
        aria-label="Filter"
        class="min-w-32 flex-1"
        :icon="icons.search"
        :loading="listingQuery.isFetching.value"
        size="sm"
        :spellcheck="false"
      >
        <template #trailing>
          <c-badge color="neutral" size="sm" variant="outline">{{ entries.length }}</c-badge>
        </template>
      </c-input>
      <template v-else-if="view === 'file' && entry != null">
        <c-text class="text-muted" variant="body3">
          {{ formatFileSize(entry.size) }} &middot; {{ formatFileTime(entry.modified) }}
        </c-text>
      </template>
      <c-text v-else-if="view === 'failure'" class="text-muted" variant="body3">
        {{ failureMessage }}
      </c-text>

      <div class="ml-auto flex shrink-0 items-center">
        <c-file-entry-actions v-if="openedActions != null" v-bind="openedActions" />
        <!-- The icon shows whether hidden entries show, the tooltip what a press does. -->
        <c-tooltip
          v-if="view === 'listing'"
          :text="persisted.hidden ? 'Hide Hidden' : 'Show Hidden'"
        >
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
        <template v-if="view === 'listing' && writable">
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
              @click="createDirectory(currentDirectory)"
            />
          </c-tooltip>
        </template>
        <!-- A browser too narrow for a side panel always previews full, so it offers no choice. -->
        <c-field-group v-if="wide" class="ml-1 shrink-0">
          <c-tooltip v-for="choice in previewChoices" :key="choice.mode" :text="choice.label">
            <c-button
              :aria-label="choice.label"
              :aria-pressed="previewSettings.mode === choice.mode"
              :class="previewSettings.mode === choice.mode && 'bg-accented'"
              color="neutral"
              :icon="choice.icon"
              size="xs"
              variant="outline"
              @click="previewSettings.mode = choice.mode"
            />
          </c-tooltip>
        </c-field-group>
      </div>
    </div>

    <div ref="root" class="relative flex min-h-0 flex-1">
      <!-- The content scrolls under the toolbar, which stays in view. -->
      <div
        class="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-auto"
        :style="side ? { flex: `0 0 ${listingWidth}px` } : undefined"
      >
        <template v-if="view === 'listing'">
          <c-text v-if="listing?.truncated" class="text-warning" variant="body3">
            Showing the first {{ listing.entries.length.toLocaleString() }} entries. The directory
            holds more than the engine lists at once.
          </c-text>
          <div
            v-if="emptyTitle != null"
            class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center"
          >
            <c-icon class="text-dimmed" :name="icons.folderOpen" size="64" />
            <c-text variant="title2">{{ emptyTitle }}</c-text>
            <template v-if="emptyTitle === 'No Visible Files'">
              <c-text class="text-muted" variant="body3">
                {{ hiddenCount.toLocaleString('en-US') }} hidden
                {{ hiddenCount === 1 ? 'item' : 'items' }}
              </c-text>
              <c-button
                color="neutral"
                :icon="icons.view"
                label="Show Hidden Files"
                size="sm"
                variant="outline"
                @click="persisted.hidden = true"
              />
            </template>
          </div>
          <!-- The column header and the rows share one frame, so they read as one table. -->
          <div v-else class="border-default rounded-md border">
            <c-context-menu :items="columnItems">
              <!-- Labels only, since the engine pages the listing by name and a page sorts
              alone. -->
              <div
                class="text-muted border-default flex shrink-0 items-center gap-2 border-b px-3 py-1 text-xs"
              >
                <span class="w-4 shrink-0" />
                <span class="min-w-0 flex-1">Name</span>
                <span
                  v-for="{ column, label } in shownColumns"
                  :key="column"
                  class="hidden shrink-0 text-right"
                  :class="columnClasses[column]"
                >
                  {{ label }}
                </span>
                <button
                  aria-haspopup="menu"
                  aria-label="Columns"
                  class="flex shrink-0 items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
                  type="button"
                  @click.stop="openContextMenu"
                  @mousedown.stop
                  @pointerdown.stop
                >
                  <c-icon :name="icons.columns" size="15" />
                </button>
              </div>
            </c-context-menu>
            <c-context-menu :items="menuItems">
              <div
                ref="list"
                class="outline-primary/25 rounded-b-md focus-visible:outline-3"
                tabindex="0"
                @contextmenu="onListContext"
                @copy="onListCopy"
                @keydown="onListKeydown"
              >
                <div class="divide-default divide-y [&>:last-child]:rounded-b-md">
                  <c-list-item
                    v-for="current in entries"
                    :key="current.name"
                    :data-file-entry="current.name"
                    selectable
                    :selected="rows.isSelected(current.name)"
                    @click="rows.onClick(current.name, $event)"
                    @contextmenu="rows.ensureSelected(current.name)"
                    @dblclick="path = [...currentDirectory, current.name]"
                  >
                    <c-icon class="shrink-0" :name="entryIcon(current)" size="16" />
                    <!-- Only the name opens the entry, the rest of the row selects it. -->
                    <c-text class="min-w-0 flex-1 truncate" variant="body3">
                      <c-link
                        class="max-w-full cursor-pointer truncate text-left align-top hover:underline"
                        raw
                        tabindex="-1"
                        v-bind="opener([...currentDirectory, current.name])"
                        @click.stop
                      >
                        {{ current.name }}
                      </c-link>
                    </c-text>
                    <c-text
                      v-for="{ column } in shownColumns"
                      :key="column"
                      class="text-muted hidden shrink-0 text-right"
                      :class="columnClasses[column]"
                      variant="body3"
                    >
                      {{ cellText(current, column) }}
                    </c-text>
                    <!-- The rows share the list's one menu, since a menu per row costs thousands of
                mounts in a long listing. -->
                    <button
                      aria-haspopup="menu"
                      :aria-label="`More Actions for ${current.name}`"
                      class="flex shrink-0 items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
                      tabindex="-1"
                      type="button"
                      @click.stop="openContextMenu"
                      @mousedown.stop
                      @pointerdown.stop
                    >
                      <c-icon :name="icons.more" size="15" />
                    </button>
                  </c-list-item>
                </div>
              </div>
            </c-context-menu>
          </div>
        </template>

        <c-file-preview
          v-else-if="(view === 'file' || view === 'other') && openedEntry != null"
          bare
          :entry="openedEntry"
          :hidden="persisted.hidden"
          :mount
          :path
        />
      </div>

      <template v-if="side">
        <!-- Mounted once measured, since the handle clamps its value on mount and a width of 0
        would clamp the saved panel width down to its minimum. -->
        <c-resize-handle
          v-if="rootWidth > 0"
          v-model="listingWidth"
          class="absolute top-0 z-10"
          direction="horizontal"
          :max="rootWidth - PREVIEW_MIN_WIDTH"
          :min="LISTING_MIN_WIDTH"
          :style="{ left: `${listingWidth + 6}px` }"
          visibility="hover"
        />
        <div
          class="border-default ml-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-auto rounded-md border p-3"
        >
          <c-file-preview
            v-if="panelTarget != null"
            :entry="panelTarget.entry"
            :hidden="persisted.hidden"
            :mount
            :path="panelTarget.path"
            @open="path = panelTarget.path"
          >
            <template #actions>
              <c-file-entry-actions v-if="panelActions != null" v-bind="panelActions" />
            </template>
          </c-file-preview>
          <div
            v-else
            class="text-muted flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center"
          >
            <c-text variant="body3">
              {{
                selectedEntries.length > 1
                  ? selectionSummary(selectedEntries)
                  : 'Select a file to preview it.'
              }}
            </c-text>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
