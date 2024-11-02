import { defineStore } from 'pinia'
import { computed } from 'vue'
import Zod from 'zod'

import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ConnectivityModel } from '@/api/shared'
import { getter } from '@/getter'

export type Status = Zod.infer<typeof StatusModel>
export const StatusModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  running: Zod.boolean(),
  enabled: Zod.boolean().nullish(),
  connectivity: ConnectivityModel.nullish(),
})

export const useStatuses = defineStore('statuses', () => {
  const client = useClient()
  const auth = useAuth()

  let mapping = $ref<Record<string, Status>>({})

  client.useStream({
    stream: {
      path: '/api/statuses',
    },
    parse: StatusModel.array(),
    onReceive: (current: Status[]) => {
      mapping = Object.fromEntries(current.map((status) => [status.address.toString(), status]))
    },
    disable: computed(() => auth.user == null),
  })

  const get = getter($$(mapping), (address: Address) => {
    return mapping[address.toString()] ?? null
  })

  return {
    get,
  }
})
