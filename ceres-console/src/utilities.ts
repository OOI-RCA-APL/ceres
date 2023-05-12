import moment, { Duration } from 'moment'
import { computed, isRef, Ref } from 'vue'

export type Plain = string | number | boolean | null | { [property: string]: Plain } | Plain[]
export type MaybeRef<T> = Ref<T> | T
export type MaybePromise<T> = Promise<T> | T

export function asRef<T>(value: MaybeRef<T>): Readonly<Ref<T>> {
  return isRef(value) ? value : computed(() => value)
}

export function hash(str: string): string {
  let result = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    result = (result << 5) - result + char
    result &= result
  }

  return new Uint32Array([result])[0].toString(36)
}

export function parseTimeDelta(value: string | number | Duration): Duration {
  if (typeof value === 'number') {
    return moment.duration(value, 'seconds')
  }
  if (!Number.isNaN(Number(value))) {
    return moment.duration(Number(value), 'seconds')
  }
  if (moment.isDuration(value)) {
    return value
  }

  function getException() {
    return new Error(
      'Invalid time-delta value.' +
        'Must be a moment duration, a number, or a string number with a unit suffix ' +
        "'ms', 's', 'm', 'h', or 'd'."
    )
  }

  if (typeof value !== 'string') {
    throw getException()
  }

  value = value.trim().toLowerCase()

  try {
    if (value.endsWith('ms')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 2))
      return moment.duration(decodedValue, 'milliseconds')
    } else if (value.endsWith('s')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'seconds')
    } else if (value.endsWith('m')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'minutes')
    } else if (value.endsWith('h')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'hours')
    } else if (value.endsWith('d')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'days')
    }
  } catch {}

  throw getException()
}

export function displayTimeDelta(
  value: number | Duration,
  options?: { decimals?: number; long?: boolean }
): string {
  const decimals = options?.decimals
  const long = options?.long ?? false

  if (typeof value === 'number') {
    value = moment.duration(value, 'seconds')
  }

  const delta = value
  if (delta.asMilliseconds() === 0) {
    return '0'
  }

  let unitValue, unit
  if (delta.asSeconds() < 1) {
    unitValue = delta.asMilliseconds()
    unit = long ? 'milliseconds' : 'ms'
  } else if (delta.asMinutes() < 1) {
    unitValue = delta.asSeconds()
    unit = long ? 'seconds' : 's'
  } else if (delta.asHours() < 1) {
    unitValue = delta.asMinutes()
    unit = long ? 'minutes' : 'm'
  } else if (delta.asDays() < 1) {
    unitValue = delta.asHours()
    unit = long ? 'hours' : 'h'
  } else {
    unitValue = delta.asDays()
    unit = long ? 'days' : 'd'
  }

  if (unitValue === 1 && long) {
    unit = unit.replace(/s$/, '')
  }

  let displayedValue
  if (decimals != null) {
    displayedValue = unitValue.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '')
  } else {
    displayedValue = unitValue
  }

  const isApproximate = Number(displayedValue) !== unitValue
  return `${isApproximate ? '~' : ''}${displayedValue}${long ? ' ' : ''}${unit}`
}
