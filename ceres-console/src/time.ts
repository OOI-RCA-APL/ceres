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

const secondsInAMinute = 60
const secondsInAnHour = secondsInAMinute * 60
const secondsInADay = secondsInAnHour * 24
const secondsInAYear = secondsInADay * 365

export function displayDuration(
  durationOrSections: Duration | number | null | undefined,
  { hideOne = false }: { hideOne?: boolean } = {}
): string {
  const seconds = moment.isDuration(durationOrSections)
    ? durationOrSections.asSeconds()
    : durationOrSections

  if (seconds == null) {
    return '?'
  }
  let divisor = 1
  let unit = 'seconds'
  if (seconds >= secondsInAYear) {
    divisor = secondsInAYear
    unit = 'years'
  } else if (seconds >= secondsInADay) {
    divisor = secondsInADay
    unit = 'days'
  } else if (seconds >= secondsInAnHour) {
    divisor = secondsInAnHour
    unit = 'hours'
  } else if (seconds >= secondsInAMinute) {
    divisor = secondsInAMinute
    unit = 'minutes'
  }

  let result = (seconds / divisor).toFixed(1)
  if (result.endsWith('.0')) {
    result = result.slice(0, result.length - '.0'.length)
    if (result === '1' && unit.endsWith('s')) {
      unit = unit.slice(0, unit.length - 's'.length)
    }
  }

  if (hideOne && result === '1') {
    return unit
  }

  return result + ' ' + unit
}
