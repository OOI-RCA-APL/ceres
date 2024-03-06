import { Address } from '@/api/address'
import { StreamOptions, useClient } from '@/api/client'
import { LogEntryFilter } from '@/api/filter'
import { DateTimeModel, LevelModel } from '@/api/shared'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

export type LogEntry = Zod.infer<typeof LogEntryModel>
export const LogEntryModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  content: Zod.string(),
})

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
