import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { debounce } from 'quasar'
import { computed, reactive, watch } from 'vue'

import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ConsoleSettingsModel, SettingModel } from '@/api/users'

export const useSettings = defineStore('settings', () => {
  const auth = useAuth()
  const client = useClient()
  const persisted = reactive(ConsoleSettingsModel.parse({}))

  async function readConsoleSettings() {
    if (auth.user == null) {
      return null
    }

    try {
      console.log('Fetching console settings...')
      const result = await client.get(`/api/settings/${auth.user.id}/__console__`, {
        parse: SettingModel(ConsoleSettingsModel),
      })

      console.log('Console settings fetched successfully.')
      if (JSON.stringify(result.value) !== JSON.stringify(persisted)) {
        persisted.workspaces = result.value.workspaces
      }
      return result
    } catch (error) {
      console.error('Failed to fetch console settings.')
      persisted.workspaces = []
      console.error(error)
      return null
    }
  }

  async function writeConsoleSettings() {
    if (auth.user == null) {
      return
    }

    console.log('Writing console settings...')
    try {
      await client.put('/api/settings', {
        data: {
          user_id: auth.user.id,
          name: '__console__',
          value: persisted,
        },
      })
    } catch (error) {
      console.error('Failed to write console settings.')
      console.error(error)
    }

    console.log('Console settings written successfully.')
  }

  const query = useQuery({
    refetchOnWindowFocus: true,
    queryKey: computed(() => ['settings', auth.user?.id]),
    queryFn: async () => {
      return readConsoleSettings()
    },
  })

  watch(
    [computed(() => auth.user?.id), persisted],
    debounce(async () => {
      await writeConsoleSettings()
    }, 250)
  )

  return {
    async load() {
      await query.suspense()
    },
    workspaces: computed({
      get: () => persisted.workspaces,
      set: (value) => (persisted.workspaces = value),
    }),
  }
})
