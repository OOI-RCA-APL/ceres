import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  FileColumnsModel,
  type FileEntry,
  TEXT_PREVIEW_LIMIT,
  copyFile,
  decodeText,
  describeFileWriteStatus,
  droppedFiles,
  fileActions,
  fileNameProblem,
  fileNameStemEnd,
  placeDestinationBlocked,
  fileColumns,
  fileInfoPlace,
  fileInfoRows,
  filesApiPath,
  filesDownloadPath,
  filesPageKey,
  filesPagePath,
  filterEntries,
  findFileMount,
  isFileMountUnder,
  formatExactFileSize,
  formatFileSize,
  highlightLanguageOf,
  fileStatQueryKey,
  isHiddenEntry,
  parseFilesRoute,
  FilePreviewSettingsModel,
  previewMode,
  previewOf,
  previewTarget,
  selectionSummary,
} from '@/api/files'
import { copyText, highlight, loadHighlightLanguage } from '@/utilities'

function file(name: string, size: number | null = 1): FileEntry {
  return { name, kind: 'file', size, modified: null, created: null }
}

function folder(name: string): FileEntry {
  return { name, kind: 'directory', size: null, modified: null, created: null }
}

describe('FilePreviewSettingsModel', () => {
  it('previews beside a 480 px panel until chosen otherwise', () => {
    expect(FilePreviewSettingsModel.parse({})).toEqual({ mode: 'side', width: 480 })
    expect(FilePreviewSettingsModel.parse({ mode: 'full', width: 300 })).toEqual({
      mode: 'full',
      width: 300,
    })
  })
})

describe('previewMode', () => {
  it('previews full below 720 px and keeps the choice before the first measure', () => {
    expect(previewMode('side', 719)).toBe('full')
    expect(previewMode('side', 720)).toBe('side')
    expect(previewMode('side', 0)).toBe('side')
    expect(previewMode('full', 1000)).toBe('full')
  })
})

describe('previewTarget', () => {
  it('previews one selected file and otherwise returns to the directory', () => {
    expect(previewTarget(['a'], [file('b')])).toEqual(['a', 'b'])
    expect(previewTarget(['a'], [{ ...file('b'), kind: 'other' }])).toEqual(['a', 'b'])
    expect(previewTarget(['a'], [folder('b')])).toEqual(['a'])
    expect(previewTarget(['a'], [file('b'), file('c')])).toEqual(['a'])
    expect(previewTarget(['a'], [])).toEqual(['a'])
  })
})

describe('selectionSummary', () => {
  it('totals the files and says so when folders are among them', () => {
    expect(selectionSummary([file('a', 1024), file('b', 1024)])).toBe(
      `2 items selected · ${formatFileSize(2048)}`,
    )
    expect(selectionSummary([file('a', 1024), folder('b')])).toBe(
      `2 items selected · ${formatFileSize(1024)} in files`,
    )
    expect(selectionSummary([folder('a'), folder('b')])).toBe('2 items selected')
  })
})

describe('previewOf', () => {
  it('shows images, videos, and audio by their extension, at any size', () => {
    expect(previewOf(file('a.PNG', 2 * TEXT_PREVIEW_LIMIT))).toBe('image')
    expect(previewOf(file('a.mp4', 2 * TEXT_PREVIEW_LIMIT))).toBe('video')
    expect(previewOf(file('a.flac', 2 * TEXT_PREVIEW_LIMIT))).toBe('audio')
  })

  it('tries any other file as text up to the limit', () => {
    expect(previewOf(file('a.csv', TEXT_PREVIEW_LIMIT))).toBe('text')
    expect(previewOf(file('abc'))).toBe('text')
    expect(previewOf(file('.png'))).toBe('text')
    expect(previewOf(file('a.csv', TEXT_PREVIEW_LIMIT + 1))).toBe('none')
  })

  it('previews nothing that is not a file', () => {
    expect(previewOf({ ...file('a.png'), kind: 'directory' })).toBe('none')
    expect(previewOf({ ...file('a.txt'), kind: 'other' })).toBe('none')
  })
})

describe('highlightLanguageOf', () => {
  it('names a grammar by extension, ignoring case', () => {
    expect(highlightLanguageOf('a.YML')).toBe('yaml')
    expect(highlightLanguageOf('a.py')).toBe('python')
    expect(highlightLanguageOf('a.mjs')).toBe('javascript')
    expect(highlightLanguageOf('a.ts')).toBe('typescript')
    expect(highlightLanguageOf('a.vue')).toBe('markup')
  })

  it('leaves plain text, unknown names and a bare dot entry plain', () => {
    expect(highlightLanguageOf('a.txt')).toBeNull()
    expect(highlightLanguageOf('a.csv')).toBeNull()
    expect(highlightLanguageOf('a.unknown')).toBeNull()
    expect(highlightLanguageOf('Dockerfile')).toBeNull()
    expect(highlightLanguageOf('.json')).toBeNull()
  })

  it('names only grammars that load', async () => {
    for (const name of ['a.ts', 'a.py', 'a.rs', 'a.toml', 'a.ini', 'a.sh', 'a.sql', 'a.md']) {
      const language = highlightLanguageOf(name)!
      await loadHighlightLanguage(language)
      expect(highlight('abc', language)).toContain('abc')
    }
  })
})

describe('filesApiPath', () => {
  it('spells a component mount in two segments and escapes every segment on its own', () => {
    expect(filesApiPath('@a.b/c', ['d e', 'f%g', '@h'])).toBe('/api/files/@a.b/c/d%20e/f%25g/@h')
    expect(filesApiPath('project')).toBe('/api/files/project')
  })
})

describe('filesPagePath', () => {
  it('leads to the mount picker without a mount', () => {
    expect(filesPagePath(null)).toBe('/files')
    expect(filesPagePath('project', ['a', 'b c'])).toBe('/files/project/a/b%20c')
  })
})

describe('parseFilesRoute', () => {
  it('reads the mount from one segment for the engine and two for a component', () => {
    expect(parseFilesRoute([])).toEqual({ mount: null, path: [] })
    expect(parseFilesRoute(['abc', '@a', 'b'])).toEqual({ mount: 'abc', path: ['@a', 'b'] })
    expect(parseFilesRoute(['@a.b', 'c', 'd'])).toEqual({ mount: '@a.b/c', path: ['d'] })
  })

  it('keeps a malformed mount whole', () => {
    expect(parseFilesRoute(['@a'])).toEqual({ mount: '@a', path: [] })
  })

  it('round trips the page path', () => {
    const segments = filesPagePath('@a.b/c', ['d']).split('/').slice(2).map(decodeURIComponent)
    expect(parseFilesRoute(segments)).toEqual({ mount: '@a.b/c', path: ['d'] })
  })
})

describe('filesPageKey', () => {
  it('keys the page by mount alone', () => {
    expect(filesPageKey(['@a.b', 'c', 'd'])).toBe(filesPageKey(['@a.b', 'c']))
    expect(filesPageKey(['abc', 'd'])).toBe('files:abc')
  })

  it('gives the mount picker its own key', () => {
    expect(filesPageKey('')).toBe('files:')
    expect(filesPageKey(undefined)).toBe('files:')
    expect(filesPageKey('abc')).toBe('files:abc')
  })
})

describe('findFileMount', () => {
  it('finds a listed mount and nothing for an unlisted one', () => {
    const mount = {
      id: 'project',
      name: 'project',
      label: 'Project',
      component: null,
      access: 'view' as const,
      temporary: false,
      reveal_paths: true,
    }
    expect(findFileMount([mount], 'project')).toBe(mount)
    expect(findFileMount([mount], 'abc')).toBeNull()
    expect(findFileMount(undefined, 'project')).toBeNull()
  })
})

describe('isFileMountUnder', () => {
  const mountOf = (component: string | null) => ({
    id: 'abc',
    name: 'abc',
    label: 'Abc',
    component,
    access: 'view' as const,
    temporary: false,
    reveal_paths: true,
  })

  it('takes the root component and those below it, and every mount without a root', () => {
    expect(isFileMountUnder(mountOf('@a'), '@a')).toBe(true)
    expect(isFileMountUnder(mountOf('@a.b'), '@a')).toBe(true)
    expect(isFileMountUnder(mountOf('@ab'), '@a')).toBe(false)
    expect(isFileMountUnder(mountOf(null), '@a')).toBe(false)
    expect(isFileMountUnder(mountOf(null), null)).toBe(true)
  })
})

describe('filterEntries', () => {
  it('keeps the entries whose names hold the filter, ignoring case', () => {
    const entries = [file('abc'), file('ABD'), file('xyz')]
    expect(filterEntries(entries, ' ab ').map((entry) => entry.name)).toEqual(['abc', 'ABD'])
    expect(filterEntries(entries, '')).toEqual(entries)
  })
})

describe('fileActions', () => {
  it('opens one entry and changes nothing in a mount it may only view', () => {
    expect(fileActions([file('a')], false, true)).toEqual([
      'open',
      'viewRaw',
      'download',
      'copy',
      'copyPath',
      'copyLink',
      'info',
    ])
    expect(fileActions([folder('a')], true, true)).toEqual([
      'open',
      'download',
      'copyPath',
      'copyLink',
      'info',
      'rename',
      'move',
      'copyTo',
      'delete',
    ])
    expect(fileActions([file('a'), folder('b')], true, true)).toEqual([
      'download',
      'copyLink',
      'move',
      'copyTo',
      'delete',
    ])
    expect(fileActions([], true, true)).toEqual([])
  })

  it('downloads files and folders, never only special files', () => {
    const special: FileEntry = { ...file('c'), kind: 'other' }
    expect(fileActions([folder('a'), folder('b')], false, true)).toContain('download')
    expect(fileActions([special, folder('b')], false, true)).toContain('download')
    expect(fileActions([special, special], false, true)).not.toContain('download')
  })

  it('copies a system path only for one entry on a mount that reveals paths', () => {
    expect(fileActions([folder('a')], false, false)).not.toContain('copyPath')
    expect(fileActions([folder('a')], false, true)).toContain('copyPath')
  })

  it('copies a link to any entries', () => {
    expect(fileActions([{ ...file('c'), kind: 'other' }], false, false)).toEqual([
      'open',
      'copyLink',
      'info',
    ])
  })

  it('copies the contents of one text file or picture', () => {
    for (const name of ['a.txt', 'a.svg', 'a.jpg']) {
      expect(fileActions([file(name)], false, false)).toContain('copy')
    }

    for (const target of [
      [file('a.mp4')],
      [file('a.wav')],
      [file('a', TEXT_PREVIEW_LIMIT + 1)],
      [file('a.svg', TEXT_PREVIEW_LIMIT + 1)],
      [folder('a')],
      [file('a.txt'), file('b.txt')],
    ]) {
      expect(fileActions(target, false, false)).not.toContain('copy')
    }
  })
})

describe('copyFile', () => {
  /** What `copyFile` wrote of `entry` as `read` answers, by clipboard type. */
  async function copied(entry: FileEntry, content: Blob): Promise<Record<string, Blob>> {
    const written: Record<string, Blob> = {}
    vi.stubGlobal(
      'ClipboardItem',
      class {
        constructor(readonly items: Record<string, Promise<Blob>>) {}
      },
    )
    vi.stubGlobal('navigator', {
      clipboard: {
        write: async (items: { items: Record<string, Promise<Blob>> }[]) => {
          for (const [type, blob] of Object.entries(items[0]?.items ?? {})) {
            written[type] = await blob
          }
        },
      },
    })
    await copyFile(entry, () => Promise.resolve(content))
    return written
  }

  const bitmap = (width: number) => ({ width, height: width, close: vi.fn() })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('copies text and an SVG as text and any other picture as a PNG', async () => {
    for (const name of ['a.txt', 'a.svg']) {
      expect(Object.keys(await copied(file(name), new Blob(['abc'])))).toEqual(['text/plain'])
    }

    const png = new Blob(['abc'], { type: 'image/png' })
    expect(await copied(file('a.png'), png)).toEqual({ 'image/png': png })

    vi.stubGlobal('createImageBitmap', () => Promise.resolve(bitmap(2)))
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((done) => done(png))
    expect(await copied(file('a.jpg'), new Blob(['abc'], { type: 'image/jpeg' }))).toEqual({
      'image/png': png,
    })
  })

  it('refuses a binary file and a picture past the pixel cap', async () => {
    await expect(copied(file('a.txt'), new Blob([new Uint8Array([0, 0, 0])]))).rejects.toThrow(
      'This file is binary.',
    )

    const large = bitmap(10_000)
    vi.stubGlobal('createImageBitmap', () => Promise.resolve(large))
    await expect(copied(file('a.jpg'), new Blob(['abc']))).rejects.toThrow(
      'Image too large to copy.',
    )
    expect(large.close).toHaveBeenCalled()
  })
})

describe('copyText', () => {
  const { execCommand } = document
  afterEach(() => {
    vi.unstubAllGlobals()
    document.execCommand = execCommand
  })

  it('copies through a selection on a page with no clipboard, and says when that fails', async () => {
    vi.stubGlobal('navigator', {})
    let copied: string | undefined
    document.execCommand = vi.fn(() => {
      copied = document.querySelector('textarea')?.value
      return true
    })
    await copyText('abc')
    expect(copied).toBe('abc')
    expect(document.querySelector('textarea')).toBeNull()

    document.execCommand = vi.fn(() => false)
    await expect(copyText('abc')).rejects.toThrow()
    expect(document.querySelector('textarea')).toBeNull()
  })
})

describe('filesDownloadPath', () => {
  it('names a whole entry or some entries of a directory, keeping dot names when asked', () => {
    expect(filesDownloadPath('project', ['a', 'b c'])).toBe('/api/files/project/a/b%20c?download')
    expect(filesDownloadPath('project', ['a'], { entries: ['b', 'c&d'], hidden: true })).toBe(
      '/api/files/project/a?download&entry=b&entry=c%26d&hidden=',
    )
  })
})

describe('fileStatQueryKey', () => {
  it('names one description per mount and path', () => {
    expect(fileStatQueryKey('abc', ['a', 'b'])).toEqual(['files', 'stat', 'abc', 'a', 'b'])
    expect(fileStatQueryKey('abc', [])).toEqual(['files', 'stat', 'abc'])
  })
})

describe('fileNameProblem', () => {
  it('refuses an empty name, a slash, and the two dot names', () => {
    expect(fileNameProblem(' abc ')).toBeNull()
    expect(fileNameProblem('.abc')).toBeNull()
    expect(fileNameProblem('  ')).toBe('Enter a name.')
    expect(fileNameProblem('a/b')).toBe('A name cannot contain a slash.')
    expect(fileNameProblem('a\\b')).toBe('A name cannot contain a slash.')
    expect(fileNameProblem('..')).toBe('A name cannot be "..".')
  })
})

describe('fileNameStemEnd', () => {
  it('stops before a file extension and selects a hidden or folder name whole', () => {
    expect(fileNameStemEnd('abc.tar.gz', 'file')).toBe(7)
    expect(fileNameStemEnd('.abc', 'file')).toBe(4)
    expect(fileNameStemEnd('abc', 'file')).toBe(3)
    expect(fileNameStemEnd('abc.d', 'directory')).toBe(5)
  })
})

describe('placeDestinationBlocked', () => {
  it('refuses the folder the entries are in and any folder inside one being moved', () => {
    const targets = [file('a'), folder('b')]
    expect(placeDestinationBlocked(['x'], ['x'], targets)).toBe(true)
    expect(placeDestinationBlocked(['x', 'b'], ['x'], targets)).toBe(true)
    expect(placeDestinationBlocked(['x', 'b', 'c'], ['x'], targets)).toBe(true)
    expect(placeDestinationBlocked(['x', 'a'], ['x'], targets)).toBe(false)
    expect(placeDestinationBlocked([], ['x'], targets)).toBe(false)
    expect(placeDestinationBlocked(['x', 'bc'], ['x'], targets)).toBe(false)
    expect(placeDestinationBlocked(['x', 'sub'], ['x'], [file('a')])).toBe(false)
  })
})

describe('decodeText', () => {
  it('reads UTF-8 and calls anything else binary', () => {
    expect(decodeText(new TextEncoder().encode('abc\n').buffer)).toBe('abc\n')
    expect(decodeText(new Uint8Array([0xff, 0xfe]).buffer)).toBeNull()
    expect(decodeText(new Uint8Array([0x61, 0x00]).buffer)).toBeNull()
  })

  it('accepts a character cut off at the end of the start of a file', () => {
    const cut = new TextEncoder().encode('a\u00e9').slice(0, 2).buffer
    expect(decodeText(cut)).toBeNull()
    expect(decodeText(cut, { partial: true })).toBe('a')
    expect(decodeText(new Uint8Array([0xff, 0x61]).buffer, { partial: true })).toBeNull()
  })
})

describe('droppedFiles', () => {
  function item(kind: 'file' | 'string', isDirectory = false) {
    return { kind, webkitGetAsEntry: () => ({ isDirectory }) as FileSystemEntry }
  }

  it('keeps files and drops the empty file a browser makes of a folder', () => {
    const files = [new File(['a'], 'a'), new File([], 'b')]
    expect(droppedFiles(files, [item('string'), item('file'), item('file', true)])).toEqual({
      files: [files[0]],
      folders: true,
    })
    expect(droppedFiles(files, [item('file'), item('file')])).toEqual({ files, folders: false })
  })
})

describe('describeFileWriteStatus', () => {
  it('prefers the engine message and names the common refusals', () => {
    expect(describeFileWriteStatus(409, 'abc')).toBe('abc')
    expect(describeFileWriteStatus(412)).toBe('A file with that name already exists.')
    expect(describeFileWriteStatus(418)).toBe('The engine answered 418.')
  })
})

describe('formatFileSize', () => {
  it('reads out the largest unit that keeps the number at one or more', () => {
    expect(formatFileSize(null)).toBe('')
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1023)).toBe('1023 B')
    expect(formatFileSize(1536)).toBe('1.5 KiB')
    expect(formatFileSize(TEXT_PREVIEW_LIMIT)).toBe('1.0 MiB')
  })
})

describe('formatExactFileSize', () => {
  it('follows the unit with the exact byte count', () => {
    expect(formatExactFileSize(1)).toBe('1 byte')
    expect(formatExactFileSize(1023)).toBe('1,023 bytes')
    expect(formatExactFileSize(1258291)).toBe('1.2 MiB (1,258,291 bytes)')
  })
})

describe('isHiddenEntry', () => {
  it('hides dot entries', () => {
    expect(isHiddenEntry(file('.abc'))).toBe(true)
    expect(isHiddenEntry(file('abc'))).toBe(false)
  })
})

describe('FileColumnsModel', () => {
  it('shows size and modified until told otherwise', () => {
    expect(FileColumnsModel.parse({})).toEqual({ size: true, modified: true, created: false })
    expect(FileColumnsModel.parse({ created: true, size: false })).toEqual({
      size: false,
      modified: true,
      created: true,
    })
    expect(fileColumns.map(({ column }) => column)).toEqual(['size', 'modified', 'created'])
  })
})

describe('fileInfoRows', () => {
  const stat = {
    ...file('abc', 1258291),
    modified: '2026-10-22T01:02:03.000Z',
    path: '/srv/abc',
  }
  const where = { name: 'abc', location: ['Stash', 'a'], writable: false }

  it('lists every fact the engine knows', () => {
    expect(fileInfoRows(stat, where)).toEqual([
      { label: 'Name', value: 'abc' },
      { label: 'Kind', value: 'File' },
      { label: 'Location', value: 'Stash / a' },
      { label: 'Full Path', value: '/srv/abc', copyable: true },
      { label: 'Size', value: '1.2 MiB (1,258,291 bytes)' },
      { label: 'Modified', value: '2026-10-22 01:02:03 UTC' },
      { label: 'Writable', value: 'No' },
    ])
  })

  it('leaves out a path the engine keeps to itself and an empty location', () => {
    const labels = fileInfoRows({ ...stat, path: null }, { ...where, location: [] }).map(
      (row) => row.label,
    )
    expect(labels).toEqual(['Name', 'Kind', 'Size', 'Modified', 'Writable'])
  })
})

describe('fileInfoPlace', () => {
  const mount = {
    id: 'abc',
    name: 'abc',
    label: 'Abc',
    component: null,
    access: 'view' as const,
    temporary: false,
    reveal_paths: true,
  }

  it('names an engine mount alone, with nothing holding it', () => {
    expect(fileInfoPlace(mount, 'Abc', [])).toEqual({ name: 'Abc', location: [] })
    expect(fileInfoPlace(mount, 'Abc', ['a', 'b'])).toEqual({ name: 'b', location: ['Abc', 'a'] })
  })

  it('leads a component mount with its component', () => {
    const owned = { ...mount, id: '@a.b/abc', component: '@a.b' }
    expect(fileInfoPlace(owned, 'Abc', [])).toEqual({ name: 'Abc', location: ['@a.b'] })
    expect(fileInfoPlace(owned, 'Abc', ['a'])).toEqual({ name: 'a', location: ['@a.b', 'Abc'] })
  })
})
