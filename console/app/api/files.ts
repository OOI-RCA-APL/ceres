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

export type FilePreview = 'text' | 'image' | 'video' | 'none'

const imageExtensions = new Set(['avif', 'bmp', 'gif', 'ico', 'jpeg', 'jpg', 'png', 'svg', 'webp'])
const videoExtensions = new Set(['m4v', 'mov', 'mp4', 'ogv', 'webm'])

/** How the page shows `entry`. A small file of any other type is tried as text, and shows as
binary when it does not decode. */
export function previewOf(entry: FileEntry): FilePreview {
  if (entry.kind !== 'file') {
    return 'none'
  }

  const dot = entry.name.lastIndexOf('.')
  const extension = dot > 0 ? entry.name.slice(dot + 1).toLowerCase() : ''
  if (imageExtensions.has(extension)) {
    return 'image'
  }

  if (videoExtensions.has(extension)) {
    return 'video'
  }

  return entry.size != null && entry.size <= TEXT_PREVIEW_LIMIT ? 'text' : 'none'
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

/** `bytes` as UTF-8 text, or null when it holds a NUL or does not decode, which marks it binary. */
export function decodeText(bytes: ArrayBuffer): string | null {
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return text.includes('\0') ? null : text
  } catch {
    return null
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

  /** The file at `path` under `root` as text, or null when it is binary. */
  async function readText(root: string, path: readonly string[]): Promise<string | null> {
    const response = await fetch(new URL(filesApiPath(root, path), window.location.href), {
      credentials: 'include',
    })
    if (!response.ok) {
      throw new Error(`The engine answered ${response.status} for "${path.join('/')}".`)
    }

    return decodeText(await response.arrayBuffer())
  }

  /** The address an element's `src` loads the file at `path` under `root` from. */
  function sourceUrl(root: string, path: readonly string[]): string {
    return getHttpUrl(filesApiPath(root, path))
  }

  /** The address that downloads the file at `path` under `root` instead of showing it. */
  function downloadUrl(root: string, path: readonly string[]): string {
    return `${filesApiPath(root, path)}?download`
  }

  return { getRoots, list, stat, readText, sourceUrl, downloadUrl }
})
