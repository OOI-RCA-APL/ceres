import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilter, RecordModel } from '@/api/entity'
import { Level, LevelModel } from '@/api/shared'

export type LogEntry = Zod.infer<typeof LogEntryModel>
export const LogEntryModel = RecordModel.extend({
  level: LevelModel,
  content: Zod.string(),
})

export type LogEntryFilter = RecordFilter &
  Partial<{
    level: Level | Level[] | null
    content_contains: string | null
    content_prefix: string | null
    content_suffix: string | null
  }>

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
