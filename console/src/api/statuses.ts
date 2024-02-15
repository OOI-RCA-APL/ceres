import { Address } from '@/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ConnectivityModel } from '@/api/shared'
import { getter } from '@/getter'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import Zod from 'zod'

export type Status = Zod.infer<typeof StatusModel>
export const StatusModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  running: Zod.boolean(),
  enabled: Zod.boolean().nullable().default(null),
  connectivity: ConnectivityModel.nullable().default(null),
})

export const useStatuses = defineStore('statuses', () => {
  const client = useClient()
  const auth = useAuth()
  const mapping = ref<Record<string, Status>>({})

  client.useStream(
    '/api/statuses',
    Zod.array(StatusModel),
    (current) => {
      mapping.value = Object.fromEntries(
        current.map((status) => [status.address.toString(), status])
      )
    },
    computed(() => ({
      disable: auth.user == null,
    }))
  )

  const get = getter(mapping, (address: Address) => {
    return mapping.value[address.toString()] ?? null
  })

  return {
    get,
  }
})
