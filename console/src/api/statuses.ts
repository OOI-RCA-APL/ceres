import { Address } from '@/address'
import { useAuth } from '@/api/auth'
import {
  ConnectivityModel,
  UseStreamOptions,
  createQueryParams,
  getWebSocketURI,
  useStream,
} from '@/api/shared'
import { getter } from '@/getter'
import { defineStore } from 'pinia'
import { MaybeRef, computed, isRef, ref } from 'vue'
import Zod from 'zod'

export type Status = Zod.infer<typeof StatusModel>
export const StatusModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  running: Zod.boolean(),
  enabled: Zod.boolean().nullable().default(null),
  connectivity: ConnectivityModel.nullable().default(null),
})

function useStatusesStream(
  params: MaybeRef<{
    address?: Address
  }>,
  onReceive: (message: Status[]) => unknown,
  options: MaybeRef<UseStreamOptions> = {}
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/statuses${createQueryParams(isRef(params) ? params.value : params)}`)
    ),
    params,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    Zod.array(StatusModel),
    onReceive,
    options
  )
}

export const useStatuses = defineStore('statuses', () => {
  const auth = useAuth()
  const mapping = ref<Record<string, Status>>({})

  useStatusesStream(
    {},
    (next) => {
      mapping.value = Object.fromEntries(next.map((status) => [status.address.toString(), status]))
    },
    computed(() => ({ disable: auth.user == null }))
  )

  const get = getter(mapping, (address: Address) => {
    return mapping.value[address.toString()] ?? null
  })

  return {
    get,
  }
})
