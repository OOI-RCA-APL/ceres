import { usePersisted } from '@/persistence'
import moment from 'moment'
import { defineStore } from 'pinia'
import { useQuasar } from 'quasar'
import { computed, watchEffect } from 'vue'

export const useSettings = defineStore('settings', () => {
  const state = usePersisted({
    schema: ({ object, number, boolean }) =>
      object({
        isDarkModeEnabled: boolean().default(true),
        statisticsDuration: number().default(60 * 30),
      }),
    methods: [{ type: 'local-storage', key: 'store/settings' }],
  })

  const quasar = useQuasar()
  watchEffect(() => {
    quasar.dark.set(state.isDarkModeEnabled)
  })

  return {
    isDarkModeEnabled: computed({
      get: () => state.isDarkModeEnabled,
      set: (value) => (state.isDarkModeEnabled = value),
    }),
    statisticsDuration: computed({
      get: () => moment.duration(state.statisticsDuration, 'seconds'),
      set: (value) => (state.statisticsDuration = value.asSeconds()),
    }),
  }
})
