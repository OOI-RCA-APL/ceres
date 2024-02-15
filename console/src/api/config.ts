import { Address } from '@/address'
import { NameStrModel, TimeDeltaModel, get } from '@/api/shared'
import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { computed } from 'vue'
import Zod from 'zod'

export type ComponentConfig = {
  name: string
  class: string
  components: ComponentConfig[]
}

export const ComponentConfigModel: Zod.ZodType<ComponentConfig> = Zod.object({
  name: NameStrModel,
  class: Zod.string(),
  components: Zod.lazy(() => Zod.array(ComponentConfigModel)),
})

export type DatabaseType = Zod.infer<typeof DatabaseTypeModel>
export const DatabaseTypeModel = Zod.enum(['sqlite', 'postgres'])

export type DatabaseRetryConfig = Zod.infer<typeof DatabaseRetryConfigModel>
export const DatabaseRetryConfigModel = Zod.object({
  timeout: TimeDeltaModel.default('PT15S'),
  interval: TimeDeltaModel.default('PT1S'),
})

const BaseDatabaseConfig = Zod.object({
  type: DatabaseTypeModel,
  engine: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
  retry: DatabaseRetryConfigModel.default(() => DatabaseRetryConfigModel.parse({})),
})

export type SQLiteDatabaseConfig = Zod.infer<typeof SQLiteDatabaseConfigModel>
export const SQLiteDatabaseConfigModel = BaseDatabaseConfig.extend({
  type: Zod.literal('sqlite'),
  path: Zod.string().nullable().default(null),
})

export type PostgresDatabaseConfig = Zod.infer<typeof PostgresDatabaseConfigModel>
export const PostgresDatabaseConfigModel = BaseDatabaseConfig.extend({
  type: Zod.literal('postgres'),
  host: Zod.string(),
  port: Zod.number(),
  database: Zod.string(),
  user: Zod.string(),
  password: Zod.string(),
})

export type DatabaseConfig = Zod.infer<typeof DatabaseConfigModel>
export const DatabaseConfigModel = Zod.discriminatedUnion('type', [
  SQLiteDatabaseConfigModel,
  PostgresDatabaseConfigModel,
])

export type ServerConfig = Zod.infer<typeof ServerConfigModel>
export const ServerConfigModel = Zod.object({
  port: Zod.number().nullable().default(null),
})

export type ConsoleConfig = Zod.infer<typeof ConsoleConfigModel>
export const ConsoleConfigModel = Zod.object({
  title: Zod.string().nullable().default(null),
  icon: Zod.string().nullable().default(null),
  favicon: Zod.string().nullable().default(null),
  dashboard: Zod.string().transform(Address.parse).nullable().default(null),
})

export type Config = Zod.infer<typeof ConfigModel>
export const ConfigModel = Zod.object({
  name: NameStrModel,
  class: Zod.string(),
  components: Zod.array(ComponentConfigModel),
  server: ServerConfigModel,
  console: ConsoleConfigModel,
  database: DatabaseConfigModel,
})

export async function getConsoleConfig(): Promise<ConsoleConfig> {
  return await get('/api/config/console', ConsoleConfigModel)
}

export const useConfig = defineStore('config', () => {
  const consoleQuery = useQuery({
    queryKey: ['config'],
    queryFn: getConsoleConfig,
    retry: true,
  })

  const console = computed(() => consoleQuery.data.value ?? <ConsoleConfig>{})

  return {
    console,
    ...consoleQuery,
  }
})
