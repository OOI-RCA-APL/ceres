import { defineStore } from 'pinia'
import { useQuasar } from 'quasar'
import { computed, watchEffect } from 'vue'

import { usePersisted } from '@/persistence'
import { duration } from '@/time'

export const usePreferences = defineStore('preferences', () => {
  const state = usePersisted({
    schema: ({ object, number, boolean }) =>
      object({
        isDarkModeEnabled: boolean().default(true),
        isDeveloperModeEnabled: boolean().default(false),
        // Whether the last workspace this user created was private, which the create dialog opens
        // on. Someone who works in private workspaces keeps getting private ones without saying so
        // every time.
        wasLastWorkspacePrivate: boolean().default(false),
        statisticsDuration: number().default(60 * 30),
      }),
    methods: [{ type: 'local-storage', key: ['store', 'preferences'] }],
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
    isDeveloperModeEnabled: computed({
      get: () => state.isDeveloperModeEnabled,
      set: (value) => (state.isDeveloperModeEnabled = value),
    }),
    wasLastWorkspacePrivate: computed({
      get: () => state.wasLastWorkspacePrivate,
      set: (value) => (state.wasLastWorkspacePrivate = value),
    }),
    statisticsDuration: computed({
      get: () => duration(state.statisticsDuration, 'seconds'),
      set: (value) => (state.statisticsDuration = value.asSeconds()),
    }),
  }
})
