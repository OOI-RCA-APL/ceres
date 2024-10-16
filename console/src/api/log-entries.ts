import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
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
  level: Zod.union([LevelModel, Zod.array(LevelModel)]).nullable(),
  content_contains: Zod.string().nullable(),
  content_prefix: Zod.string().nullable(),
  content_suffix: Zod.string().nullable(),
}).partial()

export const useLogEntries = defineStore('log-entries', () => {
  const client = useClient()

  async function getAll(filter: LogEntryFilter): Promise<LogEntry[]> {
    return await client.get(`/api/log-entries`, {
      query: filter,
      parse: Zod.array(LogEntryModel),
    })
  }

  function useStream(
    filter: MaybeRef<LogEntryFilter>,
    onReceive: (current: LogEntry) => unknown,
    options?: MaybeRef<Omit<StreamOptions, 'query'>>
  ) {
    client.useStream(
      '/api/log-entries',
      LogEntryModel,
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
