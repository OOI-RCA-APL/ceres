import { usePersisted } from '@/persistence'
import { defineStore } from 'pinia'
import { useQuasar } from 'quasar'
import { computed, watchEffect } from 'vue'

export const useSettings = defineStore('settings', () => {
  const state = usePersisted({
    schema: ({ object, boolean }) =>
      object({
        isDarkModeEnabled: boolean().default(true),
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
  }
})
