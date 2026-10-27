import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PathTemplate } from '@/path-template'

interface Vector {
  template: string
  when?: string
  zone?: string
  atoms?: string[]
  values?: Record<string, string>
  expected?: string
}

const vectors = JSON.parse(
  readFileSync(join(import.meta.dirname, '../../tests/vectors/path-template.json'), 'utf8'),
) as Record<'render' | 'invalid' | 'unrenderable', Vector[]>

const ZONES: Record<string, string> = { utc: 'UTC' }

describe('PathTemplate', () => {
  it.each(vectors.render)('renders $template', (vector) => {
    const template = new PathTemplate(vector.template, vector.atoms)
    const zone = ZONES[vector.zone ?? 'utc'] ?? vector.zone
    expect(template.render(new Date(vector.when!), zone, vector.values)).toBe(vector.expected)
  })

  it.each(vectors.invalid)('refuses $template', (vector) => {
    expect(() => new PathTemplate(vector.template)).toThrow()
  })

  it.each(vectors.unrenderable)('refuses to render $template', (vector) => {
    const template = new PathTemplate(vector.template)
    expect(() => template.render(new Date('2026-10-27T13:45:09Z'), 'UTC', vector.values)).toThrow()
  })
})
