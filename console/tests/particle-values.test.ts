import { describe, expect, it } from 'vitest'

import { html, trusted } from '@/html'
import { formatParticleValue } from '@/particle-values'

describe('formatParticleValue', () => {
  it.each([
    [1.23456, '1.23'],
    ['text', 'text'],
    [{ depth: 3 }, '{"depth":3}'],
    [undefined, '(No Value)'],
  ])('reads %j as %s', (value, read) => {
    expect(formatParticleValue(value, 2)).toBe(read)
  })
})

describe('html', () => {
  it('escapes what it interpolates', () => {
    expect(html`<b>${'<i>a</i>'}</b>`.text).toBe('<b>&lt;i&gt;a&lt;/i&gt;</b>')
  })

  it('keeps markup it built or was vouched for', () => {
    expect(html`${[html`<br />`, trusted('<i></i>')]}`.text).toBe('<br /><i></i>')
  })
})
