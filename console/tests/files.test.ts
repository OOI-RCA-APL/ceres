import { describe, expect, it } from 'vitest'

import {
  type FileEntry,
  TEXT_PREVIEW_LIMIT,
  decodeText,
  describeFileWriteStatus,
  droppedFiles,
  fileActions,
  filesApiPath,
  filesPagePath,
  filterEntries,
  findFileMount,
  formatFileSize,
  parseFilePath,
  parseFilesRoute,
  previewOf,
} from '@/api/files'

function file(name: string, size: number | null = 1): FileEntry {
  return { name, kind: 'file', size, modified: null }
}

function folder(name: string): FileEntry {
  return { name, kind: 'directory', size: null, modified: null }
}

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

describe('findFileMount', () => {
  it('finds a listed mount and nothing for an unlisted one', () => {
    const mount = {
      id: 'project',
      name: 'project',
      label: 'Project',
      component: null,
      access: 'view' as const,
      temporary: false,
    }
    expect(findFileMount([mount], 'project')).toBe(mount)
    expect(findFileMount([mount], 'abc')).toBeNull()
    expect(findFileMount(undefined, 'project')).toBeNull()
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
  it('opens one entry, downloads only files, and changes nothing in a mount it may only view', () => {
    expect(fileActions([file('a')], false)).toEqual(['open', 'download', 'copyPath'])
    expect(fileActions([folder('a')], false)).toEqual(['open', 'copyPath'])
    expect(fileActions([folder('a')], true)).toEqual(['open', 'copyPath', 'move', 'delete'])
    expect(fileActions([file('a'), folder('b')], true)).toEqual([
      'download',
      'copyPath',
      'move',
      'delete',
    ])
    expect(fileActions([folder('a'), folder('b')], false)).toEqual(['copyPath'])
    expect(fileActions([], true)).toEqual([])
  })
})

describe('parseFilePath', () => {
  it('splits on slashes and drops the empty names around them', () => {
    expect(parseFilePath('a/b c')).toEqual(['a', 'b c'])
    expect(parseFilePath('/a//b/')).toEqual(['a', 'b'])
    expect(parseFilePath('/')).toEqual([])
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
