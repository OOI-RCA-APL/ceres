import { Address } from '@/address'
import { ItemStreamFilter, StreamOptions, useClient } from '@/api/client'
import { DateTimeModel, LevelModel } from '@/api/shared'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  code: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export const useAlerts = defineStore('alerts', () => {
  const client = useClient()

  async function getAll(filter: {
    address?: Address
    search?: string
    within?: number
    after?: string
    before?: string
    limit?: number
    order?: 'new-to-old' | 'old-to-new'
  }): Promise<Alert[]> {
    return await client.request('GET', '/api/alerts', {
      query: filter,
    })
  }

  function useStream(
    filter: MaybeRef<ItemStreamFilter>,
    onReceive: (current: Alert) => unknown,
    options?: MaybeRef<StreamOptions>
  ) {
    client.useStream(
      '/api/alerts',
      AlertModel,
      onReceive,
      computed(() => ({
        query: filter,
        ...unref(options),
      }))
    )
  }

  return {
    getAll,
    useStream,
  }
})
