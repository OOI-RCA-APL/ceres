import { Address } from '@/address'
import { useAlerts } from '@/api/alerts'
import { useAuth } from '@/api/auth'
import { useComponents } from '@/api/components'
import { Config, ConfigModel, useConfig } from '@/api/config'
import { useLogEntries } from '@/api/log-entries'
import { useMessages } from '@/api/messages'
import { ErrorInfo, post, postOrError } from '@/api/shared'
import { useStatistics } from '@/api/statistics'
import { useStatuses } from '@/api/statuses'
import { useUsers } from '@/api/users'
import { defineStore } from 'pinia'
import Zod from 'zod'

export type Engine = ReturnType<typeof useEngine>

export const useEngine = defineStore('engine', () => {
  const alerts = useAlerts()
  const auth = useAuth()
  const components = useComponents()
  const config = useConfig()
  const logs = useLogEntries()
  const messages = useMessages()
  const statistics = useStatistics()
  const statuses = useStatuses()
  const users = useUsers()

  async function start(address: Address) {
    return await post('/api/start', Zod.any(), { address })
  }

  async function stop(address: Address) {
    return await post('/api/stop', Zod.any(), { address })
  }

  async function enable(address: Address) {
    return await post('/api/enable', Zod.any(), { address })
  }

  async function disable(address: Address) {
    return await post('/api/disable', Zod.any(), { address })
  }

  async function up(address: Address) {
    return await post('/api/up', Zod.any(), { address })
  }

  async function down(address: Address) {
    return await post('/api/down', Zod.any(), { address })
  }

  async function reload(): Promise<Config | ErrorInfo> {
    const result = await postOrError('/api/reload', ConfigModel)
    await auth.refresh()
    return result
  }

  return {
    alerts,
    auth,
    components,
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
