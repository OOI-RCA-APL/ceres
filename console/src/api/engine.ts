import { Address } from '@/api/address'
import { useAlerts } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { Config, ConfigModel, useConfig } from '@/api/config'
import { useLogEntries } from '@/api/log-entries'
import { useMessages } from '@/api/messages'
import { useStatistics } from '@/api/statistics'
import { useStatuses } from '@/api/statuses'
import { useSystems } from '@/api/systems'
import { useUsers } from '@/api/users'
import { defineStore } from 'pinia'

export type Engine = ReturnType<typeof useEngine>

export const useEngine = defineStore('engine', () => {
  const client = useClient()

  const alerts = useAlerts()
  const auth = useAuth()
  const systems = useSystems()
  const config = useConfig()
  const logs = useLogEntries()
  const messages = useMessages()
  const statistics = useStatistics()
  const statuses = useStatuses()
  const users = useUsers()

  async function start(address: Address) {
    return await client.post('/api/start', {
      data: { address },
    })
  }

  async function stop(address: Address) {
    return await client.post('/api/stop', {
      data: { address },
    })
  }

  async function enable(address: Address) {
    return await client.post('/api/enable', {
      data: { address },
    })
  }

  async function disable(address: Address) {
    return await client.post('/api/disable', {
      data: { address },
    })
  }

  async function up(address: Address) {
    return await client.post('/api/up', {
      data: { address },
    })
  }

  async function down(address: Address) {
    return await client.post('/api/down', {
      data: { address },
    })
  }

  async function reload(): Promise<Config> {
    const result = await client.post('/api/reload', {
      parse: ConfigModel,
    })

    await auth.refresh()

    return result
  }

  return {
    alerts,
    auth,
    systems,
    config,
    logs,
    messages,
    statistics,
    statuses,
    users,
    start,
    stop,
    enable,
    disable,
    up,
    down,
    reload,
  }
})
