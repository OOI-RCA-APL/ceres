import { useIntervalFn } from '@vueuse/core'
import dayjs, { isDayjs } from 'dayjs'
import customParseFormat from 'dayjs/plugin/customParseFormat'
import durationPlugin, { Duration as BaseDuration } from 'dayjs/plugin/duration'
import isSameOrAfter from 'dayjs/plugin/isSameOrAfter'
import isSameOrBefore from 'dayjs/plugin/isSameOrBefore'
import utcPlugin from 'dayjs/plugin/utc'
import { defineStore } from 'pinia'
import { computed } from 'vue'

dayjs.extend(utcPlugin)
dayjs.extend(durationPlugin)
dayjs.extend(customParseFormat)
dayjs.extend(isSameOrAfter)
dayjs.extend(isSameOrBefore)

export type Datetime = dayjs.Dayjs
export type DatetimeInput = dayjs.ConfigType

function isDatetime(input: any): input is Datetime {
  return isDayjs(input)
}

export function utc(
  input?: DatetimeInput | null | undefined,
  pattern?: string | ReadonlyArray<string>,
  strict?: boolean
): Datetime {
  if (Array.isArray(pattern)) {
    if (pattern.length === 0) {
      throw new Error('Pattern array must not be empty.')
    }

    const patterns = pattern
    let parsed: Datetime
    for (const pattern of patterns) {
      parsed = utc(input, pattern, strict)
      if (parsed.isValid()) {
        return parsed
      }
    }

    return parsed
  }

  if (isDatetime(input)) {
    return dayjs.utc(input)
  }

  const base = dayjs.utc(input, pattern, strict)
  if (!base.isValid()) {
    return base
  }

  // Convert ISO strings with microsecond precision to millisecond precision. This handles timezone
  // offsets including an appended 'Z' abbreviation.
  if (typeof input === 'string' && input.includes('.')) {
    const dotIndex = input.indexOf('.')
    const datePart = input.slice(0, dotIndex)
    const fractionAndTz = input.slice(dotIndex + 1)
    const match = fractionAndTz.match(/^(\d+)(Z|[+-]\d{2}:\d{2})?$/)
    if (match) {
      const ms = match[1].slice(0, 3).padEnd(3, '0')
      const tz = match[2] ?? ''
      const parsed = dayjs.utc(`${datePart}.${ms}${tz}`, pattern)
      if (parsed.isValid()) {
        return parsed
      }
    }
  }

  return base
}

// Test to ensure ISO strings with microsecond precision are converted to millisecond precision.
const value = utc('2000-01-01T00:10:10.855759Z')
if (
  value.millisecond() !== 855 ||
  !value.isValid() ||
  value.valueOf() === utc('2000-01-01T00:10:10Z').valueOf()
) {
  throw new Error()
}

export type DurationInput = string | number | Duration
export type Duration = BaseDuration

export const isDuration = dayjs.isDuration

// Wrap `dayjs.duration` to return any provided `Duration` inputs, matching the `moment.duration`
// behavior, but without cloning as DayJS values are immutable. Originally this would produce an
// invalid `Duration` which is very stupid.
export const duration: typeof dayjs.duration & ((input: Duration) => Duration) = (
  ...args: [any, ...any[]]
) => {
  if (isDuration(args[0])) {
    return args[0].clone()
  }

  return dayjs.duration(...(args as Parameters<typeof dayjs.duration>))
}

// Add isValid() to the Duration prototype.
;(dayjs.duration(0) as any).__proto__.isValid = function (this: Duration): boolean {
  return !isNaN(this.asMilliseconds())
}

if (duration('invalid').isValid()) {
  throw new Error()
}

declare module 'dayjs/plugin/duration' {
  interface Duration {
    isValid(): boolean
  }
}

export type Time = ReturnType<typeof useTime>

const secondsInAMillisecond = 0.001
const secondsInAMinute = 60
const secondsInAnHour = secondsInAMinute * 60
const secondsInADay = secondsInAnHour * 24
const secondsInAYear = secondsInADay * 365

export function displayDuration(
  durationOrSections: Duration | number | null | undefined,
  {
    hideOne = false,
    short = false,
    decimals = 1,
  }: { hideOne?: boolean; short?: boolean; decimals?: number } = {}
): string {
  const seconds = dayjs.isDuration(durationOrSections)
    ? durationOrSections.asSeconds()
    : durationOrSections

  if (seconds == null) {
    return '?'
  }
  let divisor: number
  let unit: string

  if (seconds >= secondsInAYear) {
    divisor = secondsInAYear
    unit = short ? 'y' : 'years'
  } else if (seconds >= secondsInADay) {
    divisor = secondsInADay
    unit = short ? 'd' : 'days'
  } else if (seconds >= secondsInAnHour) {
    divisor = secondsInAnHour
    unit = short ? 'h' : 'hours'
  } else if (seconds >= secondsInAMinute) {
    divisor = secondsInAMinute
    unit = short ? 'm' : 'minutes'
  } else if (seconds >= 1) {
    divisor = 1
    unit = short ? 's' : 'seconds'
  } else {
    divisor = secondsInAMillisecond
    unit = short ? 'ms' : 'milliseconds'
  }

  let result = (seconds / divisor).toFixed(decimals)
  if (result.endsWith('.0')) {
    result = result.slice(0, result.length - '.0'.length)
    if (!short && result === '1' && unit.endsWith('s')) {
      unit = unit.slice(0, unit.length - 's'.length)
    }
  }

  if (hideOne && result === '1') {
    return unit
  }

  return short ? result + unit : result + ' ' + unit
}

export const useTime = defineStore('time', () => {
  function getNow(): Datetime {
    return utc().millisecond(0)
  }

  function getNowFast(): Datetime {
    return utc()
  }

  let now = $shallowRef(getNow())
  let nowFast = $shallowRef(getNowFast())

  useIntervalFn(() => {
    const next = getNow()
    if (!now.isSame(next)) {
      now = next
    }
    const nextFast = getNowFast()
    if (!nowFast.isSame(nextFast)) {
      nowFast = nextFast
    }
  }, 50)

  return {
    now: computed(() => now),
    nowFast: computed(() => nowFast),
  }
})
