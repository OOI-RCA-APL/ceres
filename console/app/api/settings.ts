import { defineStore } from 'pinia'
import * as z from 'zod'

import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'

export function SettingModel<T extends z.ZodType>(valueModel: T) {
  return z.object({
    user_id: z.string(),
    name: z.string(),
    value: valueModel,
  })
}

/** Named per-user settings stored by the engine. */
export const useSettings = defineStore('settings', () => {
  const auth = useAuth()
  const client = useClient()

  async function get<T extends z.ZodType>(name: string, model: T): Promise<z.infer<T> | null> {
    if (auth.user == null) {
      return null
    }

    const parse = SettingModel(model) as unknown as z.ZodType<{
      user_id: string
      name: string
      value: z.infer<T>
    }>
    const setting = await client.get(`/api/settings/${auth.user.id}/${encodeURIComponent(name)}`, {
      parse,
    })
    return setting.value
  }

  async function set<T extends z.ZodType>(name: string, value: z.infer<T>) {
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

  return {
    get,
    set,
  }
})
