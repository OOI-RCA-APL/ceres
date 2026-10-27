import { defineStore } from 'pinia'
import * as z from 'zod'

import { useClient } from '@/api/client'
import { type ValueHistory, createHistory } from '@/history'
import { usePersisted } from '@/persistence'
import { utc } from '@/time'
import { type HighlightLanguage, getHttpUrl } from '@/utilities'

export type MountAccess = z.infer<typeof MountAccessModel>
/** What the caller may do with a mount, `edit` adding upload, create, rename, and delete. */
export const MountAccessModel = z.enum(['none', 'view', 'edit'])

export type FileMount = z.infer<typeof FileMountModel>
export const FileMountModel = z.object({
  /** An engine mount's name, or a component's address and the mount's name, `@rig/stills`. */
  id: z.string(),
  name: z.string(),
  label: z.string(),
  /** The address of the component whose field holds the mount, null for an engine mount. */
  component: z.string().nullable(),
  access: MountAccessModel,
  /** Whether the mount is a temporary directory, removed once the component releases it. */
  temporary: z.boolean(),
  /** Whether a stat answers where an entry lives on the server, the same for every mount. */
  reveal_paths: z.boolean(),
})

/** The mount in `mounts` with `id`, null when the caller cannot reach it. */
export function findFileMount(mounts: readonly FileMount[] | undefined, id: string) {
  return mounts?.find((mount) => mount.id === id) ?? null
}

/** Whether `mount` belongs to the component at `root` or one below it, any mount when null. */
export function isFileMountUnder(mount: FileMount, root: string | null) {
  return (
    root == null ||
    (mount.component != null &&
      (mount.component === root || mount.component.startsWith(`${root}.`)))
  )
}

export type FileKind = z.infer<typeof FileKindModel>
export const FileKindModel = z.enum(['file', 'directory', 'other'])

export type FileEntry = z.infer<typeof FileEntryModel>
export const FileEntryModel = z.object({
  name: z.string(),
  kind: FileKindModel,
  /** Bytes, null for anything but a file. */
  size: z.number().nullable(),
  modified: z.string().nullable(),
  /** Null where the filesystem keeps no birth time. */
  created: z.string().nullable(),
})

export type FileStat = z.infer<typeof FileStatModel>
export const FileStatModel = FileEntryModel.extend({
  /** Where the entry lives on the server, null when the engine does not reveal paths. */
  path: z.string().nullable(),
})

export type FileListing = z.infer<typeof FileListingModel>
export const FileListingModel = z.object({
  entries: z.array(FileEntryModel),
  /** Whether the directory holds more entries than the engine lists at once. */
  truncated: z.boolean(),
})

/** The largest file previewed as text, since a bigger one is slow to fetch and to render. */
export const TEXT_PREVIEW_LIMIT = 1024 * 1024

/** How much of a file the page reads to tell text from binary before fetching all of it. */
export const TEXT_SNIFF_LENGTH = 8 * 1024

export type FilePreview = 'text' | 'image' | 'video' | 'audio' | 'none'

const mediaExtensions = new Map<string, FilePreview>(
  (
    [
      ['image', 'avif bmp gif ico jpeg jpg png svg webp'],
      ['video', 'm4v mov mp4 ogv webm'],
      ['audio', 'aac flac m4a mp3 oga ogg opus wav weba'],
    ] as const
  ).flatMap(([preview, extensions]) =>
    extensions.split(' ').map((extension) => [extension, preview] as const),
  ),
)

/** The largest text file the preview highlights, since Prism takes a while over a long one. */
export const HIGHLIGHT_LIMIT = 256 * 1024

const highlightExtensions = new Map<string, HighlightLanguage>([
  ['json', 'json'],
  ['yaml', 'yaml'],
  ['yml', 'yaml'],
  ['toml', 'toml'],
  ['ini', 'ini'],
  ['log', 'log'],
  ['py', 'python'],
  ['rs', 'rust'],
  ['ts', 'typescript'],
  ['js', 'javascript'],
  ['mjs', 'javascript'],
  ['sh', 'bash'],
  ['bash', 'bash'],
  ['sql', 'sql'],
  ['md', 'markdown'],
  ['html', 'markup'],
  ['vue', 'markup'],
  ['xml', 'markup'],
  ['css', 'css'],
])

/** The lowercase extension of `name`, empty for none or a dot entry's leading dot alone. */
function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

/** How the page shows `entry`. A small file of any other type is tried as text, and shows as
binary when its start does not decode. */
export function previewOf(entry: FileEntry): FilePreview {
  if (entry.kind !== 'file') {
    return 'none'
  }

  return (
    mediaExtensions.get(extensionOf(entry.name)) ??
    (entry.size != null && entry.size <= TEXT_PREVIEW_LIMIT ? 'text' : 'none')
  )
}

/** What the contents of `entry` copy to the clipboard as, or null when they cannot. An SVG copies
its source as text, since Safari draws no SVG to a canvas. */
export function clipboardContentOf(entry: FileEntry): 'text' | 'image' | null {
  const preview = previewOf(entry)
  if (preview === 'image' && extensionOf(entry.name) === 'svg') {
    return entry.size != null && entry.size <= TEXT_PREVIEW_LIMIT ? 'text' : null
  }

  return preview === 'text' || preview === 'image' ? preview : null
}

/** The most pixels a copied image may have, a 256 MiB canvas at four bytes each. */
export const COPY_IMAGE_PIXEL_LIMIT = 64e6

/** A file copy the page refused, its message for the person who asked. */
export class FileCopyError extends Error {}

/** Put the contents of the file `entry` on the clipboard, as `read` fetches them. Call it inside
the click or key that asked and before any `await`, since a browser takes a clipboard item only
within that gesture and lets its contents arrive afterward. */
export async function copyFile(entry: FileEntry, read: () => Promise<Blob>): Promise<void> {
  const content = clipboardContentOf(entry)
  if (content == null) {
    throw new FileCopyError('This file cannot be copied.')
  }

  const type = content === 'text' ? 'text/plain' : 'image/png'
  const blob = read().then(content === 'text' ? textBlob : pngBlob)
  try {
    await navigator.clipboard.write([new ClipboardItem({ [type]: blob })])
  } catch (error) {
    // The browser reports a failed item as its own error, so the conversion's reason goes first.
    await blob
    throw error
  }
}

async function textBlob(blob: Blob): Promise<Blob> {
  const text = decodeText(await blob.arrayBuffer())
  if (text == null) {
    throw new FileCopyError('This file is binary.')
  }

  return new Blob([text], { type: 'text/plain' })
}

/** `blob` as a PNG, the one image type every browser's clipboard takes. */
async function pngBlob(blob: Blob): Promise<Blob> {
  if (blob.type === 'image/png') {
    return blob
  }

  const bitmap = await createImageBitmap(blob)
  try {
    if (bitmap.width * bitmap.height > COPY_IMAGE_PIXEL_LIMIT) {
      throw new FileCopyError('Image too large to copy.')
    }

    const canvas = document.createElement('canvas')
    canvas.width = bitmap.width
    canvas.height = bitmap.height
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0)
    return await new Promise((resolve, reject) => {
      canvas.toBlob(
        (png) =>
          png == null ? reject(new FileCopyError('Could not copy the image.')) : resolve(png),
        'image/png',
      )
    })
  } finally {
    bitmap.close()
  }
}

/** The grammar a text preview of the file `name` highlights with, null for plain text. */
export function highlightLanguageOf(name: string): HighlightLanguage | null {
  return highlightExtensions.get(extensionOf(name)) ?? null
}

/** `base`, then the mount's URL segments, then `path`, each segment escaped. A component
mount's ID, `<address>/<name>`, spans two segments, and `@` stays bare where a URL allows it. */
function filesUrl(base: string, mount: string, path: readonly string[]): string {
  const segments = [...mount.split('/'), ...path]
  return [
    base,
    ...segments.map((segment) => encodeURIComponent(segment).replaceAll('%40', '@')),
  ].join('/')
}

/** Split a files URL's `segments` into the mount and the path under it. An engine mount takes
one segment, its name, and a component's two, its address, which starts with `@`, and its name. A
malformed mount is kept whole, which no mount matches. */
export function parseFilesRoute(segments: readonly string[]): {
  mount: string | null
  path: string[]
} {
  const [first, second, ...rest] = segments
  if (first == null) {
    return { mount: null, path: [] }
  }

  if (first.startsWith('@') && second != null) {
    return { mount: `${first}/${second}`, path: rest }
  }

  return { mount: first, path: segments.slice(1) }
}

/** The files page's catch-all route parameter as segments. The router gives a string for one
segment and an empty string or nothing for none. */
export function filesRouteSegments(value: string | readonly string[] | undefined): string[] {
  return Array.isArray(value) ? [...value] : value != null && value !== '' ? [value as string] : []
}

/** The key the files page mounts under, one instance per mount, so moving within a mount keeps
the browser's selection and focus. */
export function filesPageKey(value: string | readonly string[] | undefined): string {
  return `files:${parseFilesRoute(filesRouteSegments(value)).mount ?? ''}`
}

/** The engine's path for `path` under `mount`. */
export function filesApiPath(mount: string, path: readonly string[] = []): string {
  return filesUrl('/api/files', mount, path)
}

/** The engine's path that downloads the file at `path` under `mount` instead of showing it, or a
directory there as one zip. `entries` narrows a directory's zip to those names in it, and `hidden`
keeps the dot names below them. */
export function filesDownloadPath(
  mount: string,
  path: readonly string[],
  { entries = [], hidden = false }: { entries?: readonly string[]; hidden?: boolean } = {},
): string {
  const query = new URLSearchParams(entries.map((name) => ['entry', name]))
  if (hidden) {
    query.set('hidden', '')
  }

  const rest = query.toString()
  return `${filesApiPath(mount, path)}?download${rest === '' ? '' : `&${rest}`}`
}

/** The query key of the description of `path` under `mount`, one for every view asking, so a
prefetch serves them all. */
export function fileStatQueryKey(mount: string, path: readonly string[]) {
  return ['files', 'stat', mount, ...path]
}

/** The query key of the text preview of `path` under `mount`, which a copy reads when cached. */
export function fileTextQueryKey(mount: string, path: readonly string[]) {
  return ['files', 'text', mount, ...path]
}

/** The console's page for `path` under `mount`, or the mount picker without a mount. */
export function filesPagePath(mount: string | null, path: readonly string[] = []): string {
  return mount == null ? '/files' : filesUrl('/files', mount, path)
}

/** A place a file view shows, a path under a mount or the list of mounts without one. */
export type FilePlace = z.infer<typeof FilePlaceModel>
export const FilePlaceModel = z.object({
  mount: z.string().nullable(),
  path: z.array(z.string()),
})

const FileHistoryStateModel = z.object({
  entries: z.array(FilePlaceModel).catch([]),
  index: z.number().int().catch(-1),
})

/** The most places one file view's Back and Forward keep. */
const FILE_HISTORY_LIMIT = 30

/** The Back and Forward history of the file view `key`, stored in local storage so it outlives a
reload and the browser remounting for another mount. */
export function useFileHistory(key: string): ValueHistory<FilePlace> {
  const state = usePersisted({
    schema: FileHistoryStateModel,
    methods: [{ type: 'local-storage', key: ['files', 'history', key] }],
  })
  return createHistory<FilePlace>({
    limit: FILE_HISTORY_LIMIT,
    clone: (place) => ({ mount: place.mount, path: [...place.path] }),
    state,
  })
}

/** `size` bytes in the largest binary unit that keeps the number at one or more. */
export function formatFileSize(size: number | null): string {
  if (size == null) {
    return ''
  }

  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const power = size < 1 ? 0 : Math.min(Math.floor(Math.log2(size) / 10), units.length - 1)
  return `${(size / 1024 ** power).toFixed(power === 0 ? 0 : 1)} ${units[power]}`
}

/** `size` in its largest unit with the exact byte count after it, `1.2 MiB (1,258,291 bytes)`. */
export function formatExactFileSize(size: number): string {
  const bytes = `${size.toLocaleString('en-US')} ${size === 1 ? 'byte' : 'bytes'}`
  return size < 1024 ? bytes : `${formatFileSize(size)} (${bytes})`
}

/** `time`, an RFC 3339 timestamp from the engine, in UTC like every console time, or blank. */
export function formatFileTime(time: string | null): string {
  return time == null ? '' : utc(time).format('YYYY-MM-DD HH:mm:ss')
}

/** Which optional listing columns show, a choice every browser shares. */
export const FileColumnsModel = z.object({
  size: z.boolean().default(true),
  modified: z.boolean().default(true),
  created: z.boolean().default(false),
})
export type FileColumns = z.infer<typeof FileColumnsModel>
export type FileColumn = keyof FileColumns

/** The optional columns in the order the listing shows them, after the name. */
export const fileColumns: readonly { column: FileColumn; label: string }[] = [
  { column: 'size', label: 'Size' },
  { column: 'modified', label: 'Modified' },
  { column: 'created', label: 'Created' },
]

export type FilePreviewMode = 'side' | 'full'

/** Whether a file previews beside the listing or in its place, and the side panel's width in px, a
choice every browser shares. */
export const FilePreviewSettingsModel = z.object({
  mode: z.enum(['side', 'full']).default('side'),
  width: z.number().default(480),
})
export type FilePreviewSettings = z.infer<typeof FilePreviewSettingsModel>

/** The narrowest side panel. */
export const PREVIEW_MIN_WIDTH = 240

/** The narrowest listing beside a side panel. */
export const LISTING_MIN_WIDTH = 320

/** The narrowest browser that previews beside its listing, since below it neither would fit. */
export const SIDE_PREVIEW_MIN_WIDTH = 720

/** The mode a browser `width` px wide previews in, given the chosen `mode`. A width of 0 is one
not yet measured, which keeps the choice so the first frame shows the layout the next one keeps. */
export function previewMode(mode: FilePreviewMode, width: number): FilePreviewMode {
  return width > 0 && width < SIDE_PREVIEW_MIN_WIDTH ? 'full' : mode
}

/** The path a side preview shows when `selected`, entries of `directory`, are selected: one file
or special entry at its own path, anything else the directory. */
export function previewTarget(directory: readonly string[], selected: readonly FileEntry[]) {
  const [only] = selected
  return selected.length === 1 && only != null && only.kind !== 'directory'
    ? [...directory, only.name]
    : [...directory]
}

/** What a side preview says of several selected entries. A directory's size says nothing of what
it holds, so a total that skips one says it counts files only. */
export function selectionSummary(selected: readonly FileEntry[]): string {
  const files = selected.filter((entry) => entry.kind === 'file')
  const count = `${selected.length.toLocaleString('en-US')} items selected`
  if (files.length === 0) {
    return count
  }

  const total = formatFileSize(files.reduce((sum, entry) => sum + (entry.size ?? 0), 0))
  return files.length === selected.length ? `${count} · ${total}` : `${count} · ${total} in files`
}

export const fileKindLabels: Record<FileKind, string> = {
  directory: 'Directory',
  file: 'File',
  other: 'Special file or link',
}

/** The name and location the Info dialog gives the entry at `target` under `mount`, labeled
`mountLabel`. Mounts of different components often share a name, so the location leads with the
component. */
export function fileInfoPlace(
  mount: FileMount | null,
  mountLabel: string,
  target: readonly string[],
): { name: string; location: string[] } {
  const component = mount?.component == null ? [] : [mount.component]
  const parents = target.length === 0 ? [] : [mountLabel, ...target.slice(0, -1)]
  return { name: target.at(-1) ?? mountLabel, location: [...component, ...parents] }
}

/** One row of the Info dialog. `copyable` puts a copy button beside the value. */
export type FileInfoRow = { label: string; value: string; copyable?: boolean }

/** The Info dialog's rows for `stat`, an entry named `name` held by `location`, outermost first. A
fact the engine does not know has no row, and neither does an empty location. */
export function fileInfoRows(
  stat: FileStat,
  { name, location, writable }: { name: string; location: readonly string[]; writable: boolean },
): FileInfoRow[] {
  const time = (label: string, value: string | null) =>
    value == null ? [] : [{ label, value: `${formatFileTime(value)} UTC` }]
  return [
    { label: 'Name', value: name },
    { label: 'Kind', value: fileKindLabels[stat.kind] },
    ...(location.length === 0 ? [] : [{ label: 'Location', value: location.join(' / ') }]),
    ...(stat.path == null ? [] : [{ label: 'Full Path', value: stat.path, copyable: true }]),
    ...(stat.size == null ? [] : [{ label: 'Size', value: formatExactFileSize(stat.size) }]),
    ...time('Modified', stat.modified),
    ...time('Created', stat.created),
    { label: 'Writable', value: writable ? 'Yes' : 'No' },
  ]
}

/** The entries whose names hold `filter`, ignoring case. */
export function filterEntries(entries: readonly FileEntry[], filter: string): FileEntry[] {
  const text = filter.trim().toLowerCase()
  return text === ''
    ? [...entries]
    : entries.filter((entry) => entry.name.toLowerCase().includes(text))
}

/** Whether `entry` is a dot entry, which the browser hides until asked to show hidden files. */
export function isHiddenEntry(entry: FileEntry): boolean {
  return entry.name.startsWith('.')
}

/** Something the file browser does to the entries picked out of one directory. */
export type FileAction =
  | 'open'
  | 'viewRaw'
  | 'download'
  | 'copy'
  | 'copyPath'
  | 'copyLink'
  | 'info'
  | 'rename'
  | 'move'
  | 'copyTo'
  | 'delete'

/** How a `FileAction` reads where it is offered, and what running it there does. */
export type FileActionView = {
  kind: FileAction
  label: string
  icon: string
  kbds?: string[]
  /** Offered but unable to run here, for the reason `description` gives. */
  disabled?: boolean
  description?: string
  run: () => void
}

/** The actions an entry shown alone offers as buttons, in order, ahead of a menu with the rest. */
export const FILE_ENTRY_BUTTONS: readonly FileAction[] = ['download', 'viewRaw', 'copyLink', 'info']

/** What applies to `targets`, in the order the toolbar lists them, the context menu regrouping
Info with Open. Opening, info and renaming take a single entry, viewing raw a single file, a
download any file or folder among them, copying contents a single file the clipboard takes, copying
a system path a single entry on a mount that reveals paths, copying links any entries, and a change
a mount the caller may edit. */
export function fileActions(
  targets: readonly FileEntry[],
  editable: boolean,
  revealPaths: boolean,
): FileAction[] {
  const [only] = targets
  if (only == null) {
    return []
  }

  const single = targets.length === 1
  return [
    ...(single ? (['open'] as const) : []),
    ...(single && only.kind === 'file' ? (['viewRaw'] as const) : []),
    ...(targets.some((entry) => entry.kind !== 'other') ? (['download'] as const) : []),
    ...(single && clipboardContentOf(only) != null ? (['copy'] as const) : []),
    ...(single && revealPaths ? (['copyPath'] as const) : []),
    'copyLink',
    ...(single ? (['info'] as const) : []),
    ...(editable && single ? (['rename'] as const) : []),
    ...(editable ? (['move', 'copyTo', 'delete'] as const) : []),
  ]
}

/** Why `name` cannot name an entry, or null when it can. The engine's refusal stays the authority,
this only answers before the request. */
export function fileNameProblem(name: string): string | null {
  const trimmed = name.trim()
  if (trimmed === '') {
    return 'Enter a name.'
  }

  if (trimmed.includes('/') || trimmed.includes('\\')) {
    return 'A name cannot contain a slash.'
  }

  return trimmed === '.' || trimmed === '..' ? `A name cannot be "${trimmed}".` : null
}

/** Where a rename's selection of `name` ends, before a file's extension and otherwise at its end. A
leading dot starts a hidden name rather than an extension. */
export function fileNameStemEnd(name: string, kind: FileKind): number {
  const dot = name.lastIndexOf('.')
  return kind === 'file' && dot > 0 ? dot : name.length
}

/** Whether `targets`, entries of `from`, cannot move or copy into `folder`: they are already
there, or a directory among them would land inside itself. */
export function placeDestinationBlocked(
  folder: readonly string[],
  from: readonly string[],
  targets: readonly FileEntry[],
): boolean {
  const startsWith = (path: readonly string[], prefix: readonly string[]) =>
    prefix.length <= path.length && prefix.every((name, index) => path[index] === name)

  return (
    (folder.length === from.length && startsWith(folder, from)) ||
    targets.some(
      (target) => target.kind === 'directory' && startsWith(folder, [...from, target.name]),
    )
  )
}

/** `bytes` as UTF-8 text, or null when it holds a NUL or does not decode, which marks it binary.
With `partial`, `bytes` is the start of a file, and a character cut off at its end still counts
as text. */
export function decodeText(bytes: ArrayBuffer, { partial = false } = {}): string | null {
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes, { stream: partial })
    return text.includes('\0') ? null : text
  } catch {
    return null
  }
}

/** The dropped `files` that are files, and whether the drop also held a folder. A browser hands
a dropped folder over as an empty file under its name, which would replace a file of that name
with nothing. `items` is the drop's `DataTransfer.items`, whose file items line up with `files`. */
export function droppedFiles(
  files: readonly File[],
  items: ArrayLike<Pick<DataTransferItem, 'kind' | 'webkitGetAsEntry'>>,
): { files: File[]; folders: boolean } {
  const fileItems = Array.from(items).filter((item) => item.kind === 'file')
  const kept = files.filter(
    (_, index) => fileItems[index]?.webkitGetAsEntry()?.isDirectory !== true,
  )
  return { files: kept, folders: kept.length < files.length }
}

/** A write the engine refused, with the sentence the page shows for it. */
export class FileWriteError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

/** The sentence for a write the engine answered with `status`, `message` its own if it sent
one. */
export function describeFileWriteStatus(status: number, message?: string): string {
  if (message != null) {
    return message
  }

  return (
    {
      400: 'That name or path is not allowed here.',
      403: 'You may not change files here.',
      404: 'Nothing is here, or you cannot reach it.',
      409: 'Something already has that name, or the directory is not empty.',
      412: 'A file with that name already exists.',
      413: 'The file is larger than the engine accepts.',
      507: 'The disk is full.',
    }[status] ?? `The engine answered ${status}.`
  )
}

/** The body a move or a copy sends, naming its destination `to`. */
function destinationBody(to: readonly string[]) {
  return {
    body: JSON.stringify({ to: to.join('/') }),
    headers: { 'Content-Type': 'application/json' },
  }
}

async function writeFile(
  method: 'PUT' | 'POST' | 'PATCH' | 'DELETE',
  mount: string,
  path: readonly string[],
  { query = '', body, headers }: { query?: string; body?: BodyInit; headers?: HeadersInit } = {},
): Promise<void> {
  const url = new URL(filesApiPath(mount, path) + query, window.location.href)
  const response = await fetch(url, { method, body, headers, credentials: 'include' })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    const message = typeof error?.message === 'string' ? error.message : undefined
    throw new FileWriteError(response.status, describeFileWriteStatus(response.status, message))
  }
}

export const useFiles = defineStore('files', () => {
  const client = useClient()

  async function getMounts(): Promise<FileMount[]> {
    return await client.get('/api/files', { parse: z.array(FileMountModel) })
  }

  /** List the directory at `path` under `mount`, dot entries included. The answer names its
  directory, so a view still showing a previous answer can tell which directory that is. */
  async function list(
    mount: string,
    path: readonly string[],
  ): Promise<FileListing & { directory: string[] }> {
    const listing = await client.get(filesApiPath(mount, path), { parse: FileListingModel })
    return { ...listing, directory: [...path] }
  }

  /** Describe the entry at `path` under `mount`, the mount itself when `path` is empty. */
  async function stat(mount: string, path: readonly string[]): Promise<FileStat> {
    return await client.get(filesApiPath(mount, path), {
      query: { stat: true },
      parse: FileStatModel,
    })
  }

  async function fetchFile(mount: string, path: readonly string[], end?: number) {
    const response = await fetch(new URL(filesApiPath(mount, path), window.location.href), {
      credentials: 'include',
      headers: end == null ? undefined : { Range: `bytes=0-${end - 1}` },
    })
    if (!response.ok) {
      throw new Error(`The engine answered ${response.status} for "${path.join('/')}".`)
    }

    return response
  }

  async function readBytes(mount: string, path: readonly string[], end?: number) {
    return await (await fetchFile(mount, path, end)).arrayBuffer()
  }

  /** The file at `path` under `mount`, typed as the engine answers it. */
  async function readBlob(mount: string, path: readonly string[]): Promise<Blob> {
    return await (await fetchFile(mount, path)).blob()
  }

  /** The file at `path` under `mount`, `size` bytes long, as text, or null when it is binary. Only
  its start is fetched for a file that turns out binary. */
  async function readText(
    mount: string,
    path: readonly string[],
    size: number,
  ): Promise<string | null> {
    if (size <= TEXT_SNIFF_LENGTH) {
      return decodeText(await readBytes(mount, path))
    }

    const start = await readBytes(mount, path, TEXT_SNIFF_LENGTH)
    if (decodeText(start, { partial: true }) == null) {
      return null
    }

    return decodeText(await readBytes(mount, path))
  }

  /** Upload `file` to `path` under `mount`. Without `replace` an existing file is kept and the
  upload fails with status 412. */
  async function upload(
    mount: string,
    path: readonly string[],
    file: Blob,
    { replace = false }: { replace?: boolean } = {},
  ): Promise<void> {
    await writeFile('PUT', mount, path, {
      body: file,
      headers: replace ? undefined : { 'If-None-Match': '*' },
    })
  }

  async function createDirectory(mount: string, path: readonly string[]): Promise<void> {
    await writeFile('PUT', mount, path, { query: '?directory' })
  }

  /** Rename or move the entry at `path` under `mount` to `to`, a path under the same mount. */
  async function move(mount: string, path: readonly string[], to: readonly string[]) {
    await writeFile('PATCH', mount, path, destinationBody(to))
  }

  /** Copy the entry at `path` under `mount` to `to`, a path under the same mount that holds
  nothing yet. A directory copies with everything in it but its symlinks. */
  async function copy(mount: string, path: readonly string[], to: readonly string[]) {
    await writeFile('POST', mount, path, destinationBody(to))
  }

  /** Delete the entry at `path` under `mount`, a directory with everything in it. */
  async function remove(mount: string, path: readonly string[]): Promise<void> {
    await writeFile('DELETE', mount, path, { query: '?recursive' })
  }

  /** The address an element's `src` loads the file at `path` under `mount` from. */
  function sourceUrl(mount: string, path: readonly string[]): string {
    return getHttpUrl(filesApiPath(mount, path))
  }

  return {
    getMounts,
    list,
    stat,
    readText,
    readBlob,
    sourceUrl,
    upload,
    createDirectory,
    move,
    copy,
    remove,
  }
})
