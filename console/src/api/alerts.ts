import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilter, RecordModel } from '@/api/entity'
import { Level, LevelModel } from '@/api/shared'

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = RecordModel.extend({
  level: LevelModel,
  code: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type AlertFilter = RecordFilter &
  Partial<{
    level: Level | Level[] | null
    code_contains: string | null
    code_prefix: string | null
    code_suffix: string | null
  }>

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
