import { defineStore } from 'pinia'
import { computed } from 'vue'
import * as z from 'zod'

import { useClient, useQuery } from '@/api/client'
import { NameStrModel } from '@/api/shared'

export const ComponentConfigModel = z.object({
  name: NameStrModel,
  class: z.string(),
  get components(): z.ZodArray<typeof ComponentConfigModel> {
    return z.array(ComponentConfigModel)
  },
})
export type ComponentConfig = z.infer<typeof ComponentConfigModel>

export type DatabaseType = z.infer<typeof DatabaseTypeModel>
export const DatabaseTypeModel = z.enum(['sqlite', 'postgres'])

const BaseDatabaseConfig = z.object({
  type: DatabaseTypeModel,
  engine: z.record(z.string(), z.unknown()).default(() => ({})),
})

export type SQLiteDatabaseConfig = z.infer<typeof SQLiteDatabaseConfigModel>
export const SQLiteDatabaseConfigModel = BaseDatabaseConfig.extend({
  type: z.literal('sqlite'),
  path: z.string().nullish(),
})

export type PostgresDatabaseConfig = z.infer<typeof PostgresDatabaseConfigModel>
export const PostgresDatabaseConfigModel = BaseDatabaseConfig.extend({
  type: z.literal('postgres'),
  host: z.string(),
  port: z.number(),
  database: z.string(),
  user: z.string(),
  password: z.string(),
})

export type DatabaseConfig = z.infer<typeof DatabaseConfigModel>
export const DatabaseConfigModel = z.discriminatedUnion('type', [
  SQLiteDatabaseConfigModel,
  PostgresDatabaseConfigModel,
])

export type ServerConfig = z.infer<typeof ServerConfigModel>
export const ServerConfigModel = z.object({
  port: z.number().nullish(),
})

export type ConsoleConfig = z.infer<typeof ConsoleConfigModel>
export const ConsoleConfigModel = z.object({
  title: z.string().nullish(),
  icon: z.string().nullish(),
  favicon: z.string().nullish(),
})

export type Config = z.infer<typeof ConfigModel>
export const ConfigModel = z.object({
  server: ServerConfigModel,
  console: ConsoleConfigModel,
  database: DatabaseConfigModel,
})

export const useConfig = defineStore('config', () => {
  const client = useClient()

  async function getConsole(): Promise<ConsoleConfig> {
    return await client.get('/api/config/console', {
      parse: ConsoleConfigModel,
    })
  }

  const consoleQuery = useQuery({
    queryKey: ['config'],
    queryFn: getConsole,
    retry: true,
  })

  const console = computed(() => consoleQuery.data.value ?? <ConsoleConfig>{})

  return {
    console,
    ...consoleQuery,
  }
})
