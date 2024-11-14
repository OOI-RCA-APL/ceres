import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { LevelModel } from '@/api/shared'
import { dataloader } from '@/utilities'

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = RecordModel.extend({
  level: LevelModel,
  type: Zod.string(),
  data: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
}).readonly()

export type AlertFilter = Zod.infer<typeof AlertFilterModel>
export const AlertFilterModel = RecordFilterModel.extend({
  level: Zod.union([LevelModel, Zod.array(LevelModel)]).nullish(),
  type_contains: Zod.string().nullish(),
  type_prefix: Zod.string().nullish(),
  type_suffix: Zod.string().nullish(),
  data_contains: Zod.string().nullish(),
  data_prefix: Zod.string().nullish(),
  data_suffix: Zod.string().nullish(),
})

export const useAlerts = defineStore('alerts', () => {
  const client = useClient()

  async function getAll(filter: AlertFilter): Promise<Alert[]> {
    return (
      await client.get('/api/alerts', {
        query: filter,
      })
    ).map(Object.freeze)
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
    getAll: dataloader<typeof getAll, Alert[]>(getAll),
    useStream,
  }
})
