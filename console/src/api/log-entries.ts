import { Address } from '@/address'
import { ItemStreamFilter, StreamOptions, useClient } from '@/api/client'
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

  async function getAll(filter: {
    address?: Address
    search?: string
    within?: number
    after?: string
    before?: string
    limit?: number
    order?: 'new-to-old' | 'old-to-new'
  }): Promise<LogEntry[]> {
    return await client.get(`/api/log-entries`, {
      query: filter,
      parse: Zod.array(LogEntryModel),
    })
  }

  function useStream(
    filter: MaybeRef<ItemStreamFilter>,
    onReceive: (current: LogEntry) => unknown,
    options?: MaybeRef<StreamOptions>
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
