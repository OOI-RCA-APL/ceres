import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { LevelModel } from '@/api/shared'

export type LogEntry = Zod.infer<typeof LogEntryModel>
export const LogEntryModel = RecordModel.extend({
  level: LevelModel,
  content: Zod.string(),
})

export type LogEntryFilter = Zod.infer<typeof LogEntryFilterModel>
export const LogEntryFilterModel = RecordFilterModel.extend({
  level: Zod.union([LevelModel, Zod.array(LevelModel)]).nullish(),
  content_contains: Zod.string().nullish(),
  content_prefix: Zod.string().nullish(),
  content_suffix: Zod.string().nullish(),
})

export const useLogEntries = defineStore('log-entries', () => {
  const client = useClient()

  async function getAll(filter: LogEntryFilter): Promise<LogEntry[]> {
    return await client.get(`/api/log-entries`, {
      query: filter,
      parse: LogEntryModel.array(),
    })
  }

  function useStream(
    filter: MaybeRef<LogEntryFilter>,
    onReceive: (current: LogEntry) => unknown,
    options?: DeepMaybeRef<StreamOptions>
  ) {
    client.useStream({
      stream: {
        path: '/api/log-entries',
        query: filter,
      },
      parse: LogEntryModel,
      onReceive,
      ...options,
    })
  }

  return {
    getAll,
    useStream,
  }
})
