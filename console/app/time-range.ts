import { CalendarDate } from '@internationalized/date'
import { defineStore } from 'pinia'
import { reactive } from 'vue'

import { displayDuration, parseDuration, utc } from '@/time'

/** A time-series window, the newest `span` milliseconds while `live` or the fixed window from
`start` to `end`, in epoch milliseconds with `end` exclusive. */
export type TimeRange =
  { mode: 'live'; span: number } | { mode: 'fixed'; start: number; end: number }

/** The window a range covers at one moment, epoch milliseconds with `end` exclusive. */
export type TimeBounds = { start: number; end: number }

const hour = 60 * 60 * 1000
const day = 24 * hour

/** The spans a range control offers in one click, each resuming live. */
export const timeRangePresets: { label: string; span: number }[] = [
  { label: '1 h', span: hour },
  { label: '6 h', span: 6 * hour },
  { label: '12 h', span: 12 * hour },
  { label: '1 d', span: day },
  { label: '7 d', span: 7 * day },
  { label: '30 d', span: 30 * day },
]

export function liveRange(span: number): TimeRange {
  return { mode: 'live', span }
}

/** A fixed range from `start` to `end`, or null when it would cover nothing. */
export function fixedRange(start: number, end: number): TimeRange | null {
  return Number.isFinite(start) && Number.isFinite(end) && end > start
    ? { mode: 'fixed', start, end }
    : null
}

export function boundsOf(range: TimeRange, now: number): TimeBounds {
  return range.mode === 'live' ? { start: now - range.span, end: now } : range
}

export function lengthOf(range: TimeRange): number {
  return range.mode === 'live' ? range.span : range.end - range.start
}

/** `range` moved one length earlier or later. A move later that reaches now follows new data
again, since nothing lies past it to show. */
export function pageRange(range: TimeRange, direction: -1 | 1, now: number): TimeRange {
  const length = lengthOf(range)
  const { start, end } = boundsOf(range, now)
  if (direction === 1 && end + length >= now) {
    return liveRange(length)
  }

  return { mode: 'fixed', start: start + direction * length, end: end + direction * length }
}

/** The range a stored `after` and `timespan` describe: live over the timespan alone, fixed from
`after` when it is set. A timespan that does not parse reads as an hour, and a bare number as
seconds. */
export function storedRange(
  after: string | null | undefined,
  timespan: string | number | null | undefined,
) {
  let span = hour
  try {
    span = parseDuration(timespan ?? '1h').asMilliseconds()
  } catch {
    // The hour stands.
  }

  if (after == null) {
    return liveRange(span)
  }

  const start = utc(after).valueOf()
  return fixedRange(start, start + span) ?? liveRange(span)
}

/** `span` as a stored timespan in its largest whole unit, such as `12h`. */
export function storedTimespan(span: number): string {
  const units: [string, number][] = [
    ['d', day],
    ['h', hour],
    ['m', 60 * 1000],
    ['s', 1000],
  ]
  for (const [unit, size] of units) {
    if (span % size === 0) {
      return `${span / size}${unit}`
    }
  }

  return `${span}ms`
}

/** The stored `after` and `timespan` that read back as `range`. */
export function storedFields(range: TimeRange): { after: string | null; timespan: string } {
  return range.mode === 'live'
    ? { after: null, timespan: storedTimespan(range.span) }
    : { after: utc(range.start).toISOString(), timespan: storedTimespan(lengthOf(range)) }
}

function spanLabel(span: number): string {
  return (
    timeRangePresets.find((preset) => preset.span === span)?.label ??
    displayDuration(span / 1000, { decimals: 0, short: true })
  )
}

/** What a range control's label reads, in UTC. */
export function describeRange(range: TimeRange): string {
  if (range.mode === 'live') {
    return `Last ${spanLabel(range.span)}`
  }

  const start = utc(range.start)
  const end = utc(range.end)
  const format = (value: typeof start) =>
    value.format(
      value.second() === 0 && value.millisecond() === 0
        ? 'YYYY-MM-DD HH:mm'
        : 'YYYY-MM-DD HH:mm:ss',
    )
  return `${format(start)} to ${format(end)} UTC`
}

/** The UTC day holding `moment`, as a calendar shows it. */
export function calendarDay(moment: number): CalendarDate {
  const value = utc(moment)
  return new CalendarDate(value.year(), value.month() + 1, value.date())
}

/** A day as a calendar names it. */
export type CalendarDay = Pick<CalendarDate, 'year' | 'month' | 'day'>

/** The fixed range covering calendar days `first` through `last` in UTC, the last day whole. */
export function calendarRange(first: CalendarDay, last: CalendarDay): TimeRange | null {
  const start = Date.UTC(first.year, first.month - 1, first.day)
  const end = Date.UTC(last.year, last.month - 1, last.day) + day
  return fixedRange(start, end)
}

/** One view's range, held apart from what it views so it outlasts a remount. `key` names the
stored default it started from, and `zoomedFrom` the range a zoom replaced. */
export type TimeRangeView = { key: string; range: TimeRange; zoomedFrom: TimeRange | null }

/** The range each view shows, by view ID. A view's range is its own, never saved, so a viewer
and an editor move it alike. */
export const useTimeRangeViews = defineStore('timeRangeViews', () => {
  const views = reactive(new Map<string, TimeRangeView>())

  /** The view `id` shows, started from `initial` the first time and again whenever its stored
  default, named by `key`, changes. */
  function ensure(id: string, key: string, initial: () => TimeRange): void {
    if (views.get(id)?.key !== key) {
      views.set(id, { key, range: initial(), zoomedFrom: null })
    }
  }

  function get(id: string): TimeRangeView | undefined {
    return views.get(id)
  }

  return { ensure, get }
})
