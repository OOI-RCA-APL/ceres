import { useIntervalFn } from '@vueuse/core'
import moment, { Moment } from 'moment'
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

  const self = {
    now: computed(() => state.now),
  }

  return self
})

function getNow(): Moment {
  return Object.freeze(moment.utc().milliseconds(0))
}

export type Time = ReturnType<typeof useTime>
