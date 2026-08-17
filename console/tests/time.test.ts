import { describe, expect, it } from 'vitest'

import { duration, utc } from '@/time'

describe('utc', () => {
  it('converts microsecond precision to millisecond precision', () => {
    const value = utc('2000-01-01T00:10:10.855759Z')

    expect(value.isValid()).toBe(true)
    expect(value.millisecond()).toBe(855)
    expect(value.valueOf()).not.toBe(utc('2000-01-01T00:10:10Z').valueOf())
  })
})

describe('duration', () => {
  it('reports an unparsable duration as invalid', () => {
    expect(duration('invalid').isValid()).toBe(false)
  })

  it('accepts a duration input', () => {
    expect(duration(duration(5, 'seconds')).asSeconds()).toBe(5)
  })
})
