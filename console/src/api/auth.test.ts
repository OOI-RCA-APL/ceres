import { describe, expect, it } from 'vitest'

import { refreshDelayMs } from '@/api/auth'
import { utc } from '@/time'

const now = utc('2026-08-03T22:00:00Z')

describe('refreshDelayMs', () => {
  it('aims a minute before the expiry', () => {
    expect(refreshDelayMs('2026-08-03T22:05:00Z', now)).toBe(4 * 60 * 1000)
  })

  it('never goes negative for an expiry already passed', () => {
    expect(refreshDelayMs('2026-08-03T21:00:00Z', now)).toBe(0)
  })

  it('caps a far expiry inside what setTimeout can count to', () => {
    // A 30 day token overflows setTimeout's signed 32 bit delay and would fire immediately,
    // which is the refresh loop this helper exists to prevent.
    const delay = refreshDelayMs('2026-09-02T22:00:00Z', now)

    expect(delay).toBeGreaterThan(0)
    expect(delay).toBeLessThanOrEqual(2 ** 31 - 1)
  })
})
