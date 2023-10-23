import { useIntervalFn } from '@vueuse/core'
import moment, { Duration, Moment } from 'moment'
import { defineStore } from 'pinia'
import { computed, reactive } from 'vue'

export const useTime = defineStore('time', () => {
  const state = reactive({
    now: getNow(),
  })

  useIntervalFn(() => {
    const next = getNow()
    if (state.now != next) {
      state.now = next
    }
  }, 50)

  return {
    now: computed(() => state.now),
  }
})

function getNow(): Moment {
  return Object.freeze(moment.utc().milliseconds(0))
}

export type Time = ReturnType<typeof useTime>

const secondsInAMillisecond = 0.001
const secondsInAMinute = 60
const secondsInAnHour = secondsInAMinute * 60
const secondsInADay = secondsInAnHour * 24
const secondsInAYear = secondsInADay * 365

export function displayDuration(
  durationOrSections: Duration | number | null | undefined,
  { hideOne = false, short = false }: { hideOne?: boolean; short?: boolean } = {}
): string {
  const seconds = moment.isDuration(durationOrSections)
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

  let result = (seconds / divisor).toFixed(1)
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
