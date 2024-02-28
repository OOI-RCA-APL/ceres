import { Address } from '@/address'
import { StreamOptions, useClient } from '@/api/client'
import { AlertFilter } from '@/api/filter'
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

  async function getAll(filter: AlertFilter): Promise<Alert[]> {
    return await client.request('GET', '/api/alerts', {
      query: filter,
    })
  }

  function useStream(
    filter: MaybeRef<AlertFilter>,
    onReceive: (current: Alert) => unknown,
    options?: MaybeRef<Omit<StreamOptions, 'query'>>
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
