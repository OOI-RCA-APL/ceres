import { CalendarDate } from '@internationalized/date'
import { describe, expect, it } from 'vitest'

import {
  boundsOf,
  calendarRange,
  describeRange,
  fixedRange,
  liveRange,
  pageRange,
  storedFields,
  storedRange,
} from '@/time-range'

const hour = 60 * 60 * 1000
const now = Date.UTC(2026, 0, 2, 12)

describe('pageRange', () => {
  it('moves a live range back by its length into a fixed one', () => {
    expect(pageRange(liveRange(hour), -1, now)).toEqual(fixedRange(now - 2 * hour, now - hour))
  })

  it('moves a fixed range later by its length', () => {
    const range = fixedRange(now - 4 * hour, now - 3 * hour)!
    expect(pageRange(range, 1, now)).toEqual(fixedRange(now - 3 * hour, now - 2 * hour))
  })

  it('follows new data again once a move later reaches now', () => {
    expect(pageRange(fixedRange(now - 2 * hour, now - hour)!, 1, now)).toEqual(liveRange(hour))
  })
})

describe('fixedRange', () => {
  it('refuses a range ending at or before its start', () => {
    expect(fixedRange(now, now)).toBeNull()
    expect(fixedRange(now, now - 1)).toBeNull()
  })
})

describe('storedRange', () => {
  it('reads a timespan alone as live', () => {
    expect(storedRange(null, '12h')).toEqual(liveRange(12 * hour))
  })

  it('reads after and timespan as fixed', () => {
    expect(storedRange('2026-01-02T00:00:00Z', '1d')).toEqual(
      fixedRange(Date.UTC(2026, 0, 2), Date.UTC(2026, 0, 3)),
    )
  })

  it('writes back what it reads', () => {
    const range = fixedRange(Date.UTC(2026, 0, 2), Date.UTC(2026, 0, 2, 6))!
    const { after, timespan } = storedFields(range)
    expect(storedRange(after, timespan)).toEqual(range)
    expect(storedFields(liveRange(6 * hour))).toEqual({ after: null, timespan: '6h' })
  })
})

describe('calendarRange', () => {
  it('covers its last day whole, ending at the next midnight UTC', () => {
    expect(calendarRange(new CalendarDate(2026, 1, 2), new CalendarDate(2026, 1, 2))).toEqual(
      fixedRange(Date.UTC(2026, 0, 2), Date.UTC(2026, 0, 3)),
    )
  })
})

describe('describeRange', () => {
  it('names a live range by its span and a fixed one by its ends', () => {
    expect(describeRange(liveRange(12 * hour))).toBe('Last 12 h')
    expect(describeRange(fixedRange(Date.UTC(2026, 0, 2), Date.UTC(2026, 0, 3))!)).toBe(
      '2026-01-02 00:00 to 2026-01-03 00:00 UTC',
    )
  })

  it('reads bounds of a live range back from now', () => {
    expect(boundsOf(liveRange(hour), now)).toEqual({ start: now - hour, end: now })
  })
})
