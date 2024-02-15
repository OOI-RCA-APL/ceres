import { Address } from '@/address'
import {
  DateTimeModel,
  ItemStreamFilter,
  LevelModel,
  UseStreamOptions,
  createQueryParams,
  get,
  getWebSocketURI,
  useStream,
} from '@/api/shared'
import { defineStore } from 'pinia'
import { MaybeRef, computed, isRef } from 'vue'
import Zod from 'zod'

export type LogEntry = Zod.infer<typeof LogEntryModel>
export const LogEntryModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  content: Zod.string(),
})

export async function getLogEntries(params: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<LogEntry[]> {
  return await get(`/api/log-entries${createQueryParams(params)}`, Zod.array(LogEntryModel))
}

export function useLogEntryStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (entry: LogEntry, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/log-entries${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    LogEntryModel,
    onReceive,
    options
  )
}

export const useLogEntries = defineStore('log-entries', () => {
  return {
    getAll: getLogEntries,
    useStream: useLogEntryStream,
  }
})
