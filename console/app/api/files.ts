import { defineStore } from 'pinia'
import * as z from 'zod'

import { useClient } from '@/api/client'
import { ComponentAccessLevelModel } from '@/api/permissions'
import { getHttpUrl } from '@/utilities'

export type FileRoot = z.infer<typeof FileRootModel>
export const FileRootModel = z.object({
  /** Opaque, assigned by the engine, safe in a path once escaped. */
  id: z.string(),
  label: z.string(),
  /** The address of the component whose field declares the root, null for the project root. */
  component: z.string().nullable(),
  level: ComponentAccessLevelModel,
  /** Whether the caller may upload, create, rename, and delete under the root. */
  writable: z.boolean(),
})

export type FileKind = z.infer<typeof FileKindModel>
export const FileKindModel = z.enum(['file', 'directory', 'other'])

export type FileEntry = z.infer<typeof FileEntryModel>
export const FileEntryModel = z.object({
  name: z.string(),
  kind: FileKindModel,
  /** Bytes, null for anything but a file. */
  size: z.number().nullable(),
  modified: z.string().nullable(),
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

/** How the page shows `entry`. A small file of any other type is tried as text, and shows as
binary when its start does not decode. */
export function previewOf(entry: FileEntry): FilePreview {
  if (entry.kind !== 'file') {
    return 'none'
  }

  const dot = entry.name.lastIndexOf('.')
  const extension = dot > 0 ? entry.name.slice(dot + 1).toLowerCase() : ''
  return (
    mediaExtensions.get(extension) ??
    (entry.size != null && entry.size <= TEXT_PREVIEW_LIMIT ? 'text' : 'none')
  )
}

/** The engine's path for `path` under `root`, each segment escaped. */
export function filesApiPath(root: string, path: readonly string[] = []): string {
  return ['/api/files', ...[root, ...path].map(encodeURIComponent)].join('/')
}

/** The console's page for `path` under `root`, or the root picker without a root. */
export function filesPagePath(root: string | null, path: readonly string[] = []): string {
  return root == null ? '/files' : ['/files', ...[root, ...path].map(encodeURIComponent)].join('/')
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

/** The entries whose names hold `filter`, ignoring case. */
export function filterEntries(entries: readonly FileEntry[], filter: string): FileEntry[] {
  const text = filter.trim().toLowerCase()
  return text === ''
    ? [...entries]
    : entries.filter((entry) => entry.name.toLowerCase().includes(text))
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

async function writeFile(
  method: 'PUT' | 'PATCH' | 'DELETE',
  root: string,
  path: readonly string[],
  { query = '', body, headers }: { query?: string; body?: BodyInit; headers?: HeadersInit } = {},
): Promise<void> {
  const url = new URL(filesApiPath(root, path) + query, window.location.href)
  const response = await fetch(url, { method, body, headers, credentials: 'include' })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    const message = typeof error?.message === 'string' ? error.message : undefined
    throw new FileWriteError(response.status, describeFileWriteStatus(response.status, message))
  }
}

export const useFiles = defineStore('files', () => {
  const client = useClient()

  async function getRoots(): Promise<FileRoot[]> {
    return await client.get('/api/files', { parse: z.array(FileRootModel) })
  }

  /** List the directory at `path` under `root`, dot entries included when `hidden`. */
  async function list(
    root: string,
    path: readonly string[],
    { hidden = false }: { hidden?: boolean } = {},
  ): Promise<FileListing> {
    return await client.get(filesApiPath(root, path), {
      query: hidden ? { hidden: true } : null,
      parse: FileListingModel,
    })
  }

  /** Describe the entry at `path` under `root`, the root itself when `path` is empty. */
  async function stat(root: string, path: readonly string[]): Promise<FileEntry> {
    return await client.get(filesApiPath(root, path), {
      query: { stat: true },
      parse: FileEntryModel,
    })
  }

  async function readBytes(root: string, path: readonly string[], end?: number) {
    const response = await fetch(new URL(filesApiPath(root, path), window.location.href), {
      credentials: 'include',
      headers: end == null ? undefined : { Range: `bytes=0-${end - 1}` },
    })
    if (!response.ok) {
      throw new Error(`The engine answered ${response.status} for "${path.join('/')}".`)
    }

    return await response.arrayBuffer()
  }

  /** The file at `path` under `root`, `size` bytes long, as text, or null when it is binary. Only
  its start is fetched for a file that turns out binary. */
  async function readText(
    root: string,
    path: readonly string[],
    size: number,
  ): Promise<string | null> {
    if (size <= TEXT_SNIFF_LENGTH) {
      return decodeText(await readBytes(root, path))
    }

    const start = await readBytes(root, path, TEXT_SNIFF_LENGTH)
    if (decodeText(start, { partial: true }) == null) {
      return null
    }

    return decodeText(await readBytes(root, path))
  }

  /** Upload `file` to `path` under `root`. Without `replace` an existing file is kept and the
  upload fails with status 412. */
  async function upload(
    root: string,
    path: readonly string[],
    file: Blob,
    { replace = false }: { replace?: boolean } = {},
  ): Promise<void> {
    await writeFile('PUT', root, path, {
      body: file,
      headers: replace ? undefined : { 'If-None-Match': '*' },
    })
  }

  async function createDirectory(root: string, path: readonly string[]): Promise<void> {
    await writeFile('PUT', root, path, { query: '?directory' })
  }

  /** Rename or move the entry at `path` under `root` to `to`, a path under the same root. */
  async function move(root: string, path: readonly string[], to: readonly string[]) {
    await writeFile('PATCH', root, path, {
      body: JSON.stringify({ to: to.join('/') }),
      headers: { 'Content-Type': 'application/json' },
    })
  }

  /** Delete the entry at `path` under `root`, a directory with everything in it. */
  async function remove(root: string, path: readonly string[]): Promise<void> {
    await writeFile('DELETE', root, path, { query: '?recursive' })
  }

  /** The address an element's `src` loads the file at `path` under `root` from. */
  function sourceUrl(root: string, path: readonly string[]): string {
    return getHttpUrl(filesApiPath(root, path))
  }

  /** The address that downloads the file at `path` under `root` instead of showing it. */
  function downloadUrl(root: string, path: readonly string[]): string {
    return `${filesApiPath(root, path)}?download`
  }

  return {
    getRoots,
    list,
    stat,
    readText,
    sourceUrl,
    downloadUrl,
    upload,
    createDirectory,
    move,
    remove,
  }
})
