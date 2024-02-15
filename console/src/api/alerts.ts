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

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  code: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

async function getAlerts(filter: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<Alert[]> {
  return await get(`/api/alerts${createQueryParams(filter)}`, Zod.array(AlertModel))
}

function useAlertStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (alert: Alert, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/alerts${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    AlertModel,
    onReceive,
    options
  )
}

export const useAlerts = defineStore('alerts', () => {
  return {
    getAll: getAlerts,
    useStream: useAlertStream,
  }
})
