import { defineStore } from 'pinia'

import { useAccess } from '@/api/access'
import { AddressSelector } from '@/api/address'
import { useAlerts } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { useComponents } from '@/api/components'
import { Config, ConfigModel, useConfig } from '@/api/config'
import { useGroups } from '@/api/groups'
import { useLogs } from '@/api/logs'
import { useMessages } from '@/api/messages'
import { useParticles } from '@/api/particles'
import { usePermissions } from '@/api/permissions'
import { useStatistics } from '@/api/statistics'
import { useStatuses } from '@/api/statuses'
import { useUsers } from '@/api/users'
import { useWorkspaces } from '@/workspace'

export type Engine = ReturnType<typeof useEngine>

export const useEngine = defineStore('engine', () => {
  const client = useClient()

  const auth = useAuth()
  const components = useComponents()
  const config = useConfig()
  const groups = useGroups()
  const messages = useMessages()
  const particles = useParticles()
  const access = useAccess()
  const permissions = usePermissions()
  const alerts = useAlerts()
  const logs = useLogs()
  const statistics = useStatistics()
  const statuses = useStatuses()
  const users = useUsers()
  const workspaces = useWorkspaces()

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
    access,
    alerts,
    auth,
    components,
    config,
    groups,
    logs,
    messages,
    particles,
    permissions,
    statistics,
    statuses,
    users,
    workspaces,
    start,
    stop,
    enable,
    disable,
    up,
    down,
    reload,
  }
})
