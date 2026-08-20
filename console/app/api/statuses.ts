import { defineStore } from 'pinia'
import { computed } from 'vue'
import * as z from 'zod'

import { type Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ConnectivityModel } from '@/api/shared'

export type ConnectionStatus = z.infer<typeof ConnectionStatusModel>
export const ConnectionStatusModel = z.object({
  name: z.string(),
  label: z.string().nullish(),
  description: z.string().nullish(),
  uri: z.string(),
  connectivity: ConnectivityModel,
})

export type Status = z.infer<typeof StatusModel>
export const StatusModel = z.object({
  address: AddressModel,
  running: z.boolean(),
  enabled: z.boolean().nullish(),
  connectivity: ConnectivityModel.nullish(),
  connections: z.array(ConnectionStatusModel).default([]),
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

  function get(address: Address) {
    return mapping[address.toString()] ?? null
  }

  return {
    get,
  }
})
