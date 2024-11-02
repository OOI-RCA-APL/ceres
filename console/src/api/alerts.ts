import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { LevelModel } from '@/api/shared'

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = RecordModel.extend({
  level: LevelModel,
  code: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type AlertFilter = Zod.infer<typeof AlertFilterModel>
export const AlertFilterModel = RecordFilterModel.extend({
  level: Zod.union([LevelModel, Zod.array(LevelModel)]).nullish(),
  code_contains: Zod.string().nullish(),
  code_prefix: Zod.string().nullish(),
  code_suffix: Zod.string().nullish(),
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
    options?: DeepMaybeRef<StreamOptions>
  ) {
    client.useStream({
      stream: {
        path: '/api/alerts',
        query: filter,
      },
      parse: AlertModel as any,
      onReceive,
      ...options,
    })
  }

  return {
    getAll,
    useStream,
  }
})
