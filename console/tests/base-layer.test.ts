import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function vueFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry)
    if (statSync(path).isDirectory()) {
      return vueFiles(path)
    }

    return path.endsWith('.vue') ? [path] : []
  })
}

describe('base layer', () => {
  it('is the only consumer of Nuxt UI components', () => {
    for (const path of vueFiles(join(import.meta.dirname, '../app'))) {
      const source = readFileSync(path, 'utf8')
      expect(source, `${path} uses a raw Nuxt UI component`).not.toMatch(/<U[A-Z]|<u-/)
    }
  })
})
