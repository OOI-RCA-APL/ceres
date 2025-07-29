import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { debounce } from 'quasar'
import { reactive, watch } from 'vue'
import Zod, { ZodTypeAny } from 'zod'

import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'

export type ConsoleSettings = Zod.infer<typeof ConsoleSettingsModel>
export const ConsoleSettingsModel = Zod.object({})

export function SettingModel<T extends ZodTypeAny>(valueModel: T) {
  return Zod.object({
    user_id: Zod.string(),
    name: Zod.string(),
    value: valueModel,
  })
}

export const useSettings = defineStore('settings', () => {
  const auth = useAuth()
  const client = useClient()
  const settings = reactive(ConsoleSettingsModel.parse({}))

  let writes = BigInt(0)
  let ignoreWritesUpTo = BigInt(0)

  function unwritten(update: () => void) {
    ignoreWritesUpTo = writes + BigInt(1)
    update()
  }

  async function get<T extends ZodTypeAny>(name: string, model: T): Promise<Zod.infer<T>> {
    if (auth.user == null) {
      return null
    }

    return (
      await client.get(`/api/settings/${auth.user.id}/${encodeURIComponent(name)}`, {
        parse: SettingModel(model),
      })
    ).value
  }

  async function set<T extends ZodTypeAny>(name: string, value: Zod.infer<T>) {
    if (auth.user == null) {
      return
    }

    return await client.put('/api/settings', {
      data: {
        user_id: auth.user.id,
        name: name,
        value: value,
      },
    })
  }

  async function readConsoleSettings() {
    if (auth.user == null) {
      console.log('Currently logged out, no console settings to fetch.')
      return null
    }

    try {
      console.log('Fetching console settings...')
      const result = await get('__console__', ConsoleSettingsModel)

      console.log('Console settings fetched successfully.')
      if (JSON.stringify(result) !== JSON.stringify(settings)) {
        unwritten(() => {
          // Update stores here.
        })
      }

      return result
    } catch (error) {
      console.error('Failed to fetch console settings.')
      unwritten(() => {
        // Update stores here.
      })
      return null
    }
  }

  async function writeConsoleSettings(settings: ConsoleSettings) {
    if (auth.user == null) {
      return
    }

    console.log('Writing console settings...')
    try {
      await set('__console__', settings)
    } catch (error) {
      console.error('Failed to write console settings.')
      console.error(error)
    }

    console.log('Console settings written successfully.')
  }

  const debouncedWriteConsoleSettings = debounce(writeConsoleSettings, 250)

  const query = useQuery({
    queryKey: [],
    queryFn: async () => {
      return await readConsoleSettings()
    },
  })

  watch(
    () => auth.user?.id ?? null,
    () => {
      console.log('User ID changed, refetching console settings...')
      query.refetch()
    }
  )

  watch(settings, () => {
    writes++
    if (writes > ignoreWritesUpTo) {
      debouncedWriteConsoleSettings(settings)
    }
  })

  return {
    async load() {
      await query.suspense()
    },
    get,
    set,
  }
})
