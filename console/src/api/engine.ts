import { defineStore } from 'pinia'

import { AddressSelector } from '@/api/address'
import { useAlerts } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { useComponents } from '@/api/components'
import { Config, ConfigModel, useConfig } from '@/api/config'
import { useLogEntries } from '@/api/log-entries'
import { useMessages } from '@/api/messages'
import { useParticles } from '@/api/particles'
import { useStatistics } from '@/api/statistics'
import { useStatuses } from '@/api/statuses'
import { useUsers } from '@/api/users'

export type Engine = ReturnType<typeof useEngine>

export const useEngine = defineStore('engine', () => {
  const client = useClient()

  const auth = useAuth()
  const components = useComponents()
  const config = useConfig()
  const messages = useMessages()
  const particles = useParticles()
  const alerts = useAlerts()
  const logs = useLogEntries()
  const statistics = useStatistics()
  const statuses = useStatuses()
  const users = useUsers()

  async function start(address: AddressSelector) {
    return await client.post('/api/start', {
      data: { address },
    })
  }

  async function stop(address: AddressSelector) {
    return await client.post('/api/stop', {
      data: { address },
    })
  }

  async function enable(address: AddressSelector) {
    return await client.post('/api/enable', {
      data: { address },
    })
  }

  async function disable(address: AddressSelector) {
    return await client.post('/api/disable', {
      data: { address },
    })
  }

  async function up(address: AddressSelector) {
    return await client.post('/api/up', {
      data: { address },
    })
  }

  async function down(address: AddressSelector) {
    return await client.post('/api/down', {
      data: { address },
    })
  }

  async function reload(): Promise<Config> {
    const result = await client.post('/api/reload', {
      parse: ConfigModel,
    })

    await auth.refresh()
    await components.refetch()

    return result
  }

  return {
    alerts,
    auth,
    components,
    config,
    logs,
    messages,
    particles,
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
