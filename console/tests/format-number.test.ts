import { describe, expect, it } from 'vitest'

import { formatNumber } from '@/utilities'

describe('formatNumber', () => {
  it('caps the decimals it reads out', () => {
    expect(formatNumber(-19.93249999, 2)).toBe('-19.93')
  })

  it('shows no decimals on a value that has none to show', () => {
    expect(formatNumber(28, 2)).toBe('28')
    expect(formatNumber(1.5, 2)).toBe('1.5')
  })

  it('groups the thousands a gauge reads in', () => {
    expect(formatNumber(15568.117396, 2)).toBe('15,568.12')
  })

  it('reads a whole number out when told to show no decimals', () => {
    expect(formatNumber(15568.9, 0)).toBe('15,569')
  })

  it('leaves a value that is not a number to speak for itself', () => {
    expect(formatNumber(Number.NaN, 2)).toBe('NaN')
    expect(formatNumber(Number.POSITIVE_INFINITY, 2)).toBe('Infinity')
  })
})
