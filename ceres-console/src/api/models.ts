import { Address } from '@/address'
import moment from 'moment'
import Zod, { ZodTypeAny } from 'zod'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

const DateTimeModel = Zod.string()
  .refine((value) => moment.utc(value).isValid())
  .transform((value) => Object.freeze(moment.utc(value)))

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  direction: MessageDirectionModel,
  content: Zod.string(),
})

export type Level = Zod.infer<typeof LevelModel>
export const LevelModel = Zod.enum(['debug', 'info', 'warning', 'error', 'critical'])

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  code: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type LogEntry = Zod.infer<typeof LogEntryModel>
export const LogEntryModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  level: LevelModel,
  content: Zod.string(),
})

export type Item = Message | Alert | LogEntry

export type LevelStatistics = Zod.infer<typeof LevelStatisticsModel>
export const LevelStatisticsModel = Zod.object({
  level: LevelModel,
  count: Zod.number(),
})

export type AlertStatistics = Zod.infer<typeof AlertStatisticsModel>
export const AlertStatisticsModel = Zod.object({
  count: Zod.number(),
  levels: Zod.array(LevelStatisticsModel),
})

export type Statistics = Zod.infer<typeof StatisticsModel>
export const StatisticsModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  alerts: AlertStatisticsModel,
})

export type ComponentRole = Zod.infer<typeof ComponentRoleModel>
export const ComponentRoleModel = Zod.enum([
  'alerter',
  'connection',
  'dispatcher',
  'notifier',
  'ui',
])

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

export type ServerConfig = Zod.infer<typeof ServerConfigModel>
export const ServerConfigModel = Zod.object({
  port: Zod.number(),
  enable: Zod.boolean(),
})

export type DatabaseKind = Zod.infer<typeof DatabaseKindModel>
export const DatabaseKindModel = Zod.enum(['sqlite', 'postgres'])

export type DatabaseRetryConfig = Zod.infer<typeof DatabaseRetryConfigModel>
export const DatabaseRetryConfigModel = Zod.object({
  timeout: Zod.number().default(15),
  interval: Zod.number().default(3),
})

const BaseDatabaseConfig = Zod.object({
  kind: DatabaseKindModel,
  engine: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
  retry: DatabaseRetryConfigModel.default(() => DatabaseRetryConfigModel.parse({})),
})

export type SQLiteDatabaseConfig = Zod.infer<typeof SQLiteDatabaseConfigModel>
export const SQLiteDatabaseConfigModel = BaseDatabaseConfig.extend({
  kind: Zod.literal('sqlite'),
  path: Zod.string().nullable().default(null),
})

export type PostgresDatabaseConfig = Zod.infer<typeof PostgresDatabaseConfigModel>
export const PostgresDatabaseConfigModel = BaseDatabaseConfig.extend({
  kind: Zod.literal('postgres'),
  host: Zod.string(),
  port: Zod.number(),
  database: Zod.string(),
  user: Zod.string(),
  password: Zod.string(),
})

export type DatabaseConfig = Zod.infer<typeof DatabaseConfigModel>
export const DatabaseConfigModel = Zod.discriminatedUnion('kind', [
  SQLiteDatabaseConfigModel,
  PostgresDatabaseConfigModel,
])

export type Config = Zod.infer<typeof ConfigModel>
export const ConfigModel = Zod.object({
  name: Zod.string().nullable().default(''),
  server: ServerConfigModel,
  database: DatabaseConfigModel,
  components: Zod.array(ComponentConfigModel).default(() => []),
})

export type DisplayBinding = Zod.infer<typeof DisplayBindingModel>
export const DisplayBindingModel = Zod.object({
  kind: Zod.literal('display'),
  name: Zod.string(),
  function: Zod.string(),
})

export type LayoutDisplay = Zod.infer<typeof LayoutDisplayModel>
export const LayoutDisplayModel = Zod.object({
  kind: Zod.literal('display'),
  title: Zod.string(),
  procedure: Zod.string(),
})

export type LayoutRow = {
  kind: 'row'
  children: LayoutNode[]
}

export const LayoutRowModel: Zod.ZodType<LayoutRow> = Zod.object({
  kind: Zod.literal('row'),
  children: Zod.lazy(() => Zod.array(LayoutNodeModel)),
})

export type LayoutColumn = {
  kind: 'column'
  children: LayoutNode[]
}

export const LayoutColumnModel: Zod.ZodType<LayoutColumn> = Zod.object({
  kind: Zod.literal('column'),
  children: Zod.lazy(() => Zod.array(LayoutNodeModel)),
})

export type LayoutCarousel = {
  kind: 'carousel'
  children: LayoutNode[]
  height?: number | string | null
}

export const LayoutCarouselModel: Zod.ZodType<LayoutCarousel> = Zod.object({
  kind: Zod.literal('carousel'),
  children: Zod.lazy(() => Zod.array(LayoutNodeModel)),
  height: Zod.union([Zod.string(), Zod.number(), Zod.null()]).optional().default(null),
})

export type LayoutNode = Zod.infer<typeof LayoutNodeModel>
export const LayoutNodeModel = Zod.union([
  LayoutDisplayModel,
  LayoutColumnModel,
  LayoutRowModel,
  LayoutCarouselModel,
])

export type Layout = Zod.infer<typeof LayoutModel>
export const LayoutModel = Zod.object({
  body: LayoutNodeModel,
})

export type ProcedureKind = Zod.infer<typeof ProcedureKindModel>
export const ProcedureKindModel = Zod.enum(['query', 'action'])

export type ProcedureArgsInfo = Zod.infer<typeof ProcedureArgsInfoModel>
export const ProcedureArgsInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
  required: Zod.boolean(),
})

export type ProcedureOutputInfo = Zod.infer<typeof ProcedureOutputInfoModel>
export const ProcedureOutputInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
})

const BaseProcedureInfoModel = Zod.object({
  name: Zod.string(),
  kind: ProcedureKindModel,
  live: Zod.boolean(),
  args: ProcedureArgsInfoModel,
  output: ProcedureOutputInfoModel,
})

export type QueryInfo = Zod.infer<typeof QueryInfoModel>
export const QueryInfoModel = BaseProcedureInfoModel.extend({
  kind: Zod.literal('query'),
})

export type ActionInfo = Zod.infer<typeof ActionInfoModel>
export const ActionInfoModel = BaseProcedureInfoModel.extend({
  kind: Zod.literal('action'),
})

export type ProcedureInfo = Zod.infer<typeof ProcedureInfoModel>
export const ProcedureInfoModel = Zod.discriminatedUnion('kind', [QueryInfoModel, ActionInfoModel])

export type ComponentInfo = {
  name: string
  address: Address
  config: ComponentConfig
  roles: ComponentRole[]
  procedures: ProcedureInfo[]
  components: ComponentInfo[]
}

export const ComponentInfoModel: Zod.ZodType<ComponentInfo> = Zod.object({
  name: Zod.string(),
  address: Zod.string().transform(Address.parse),
  config: ComponentConfigModel,
  roles: Zod.array(ComponentRoleModel),
  procedures: Zod.array(ProcedureInfoModel),
  components: Zod.lazy(() => Zod.array(ComponentInfoModel)),
}) as any

export type Ok<TValue> = {
  ok: true
  value: TValue
}

export type Fail<TError> = {
  ok: false
  error: TError
}

export type Result<TValue, TError = unknown> = Ok<TValue> | Fail<TError>

export function ResultModel<TValueModel extends ZodTypeAny, TErrorModel extends ZodTypeAny>(
  valueModel: TValueModel,
  errorModel?: TErrorModel
): Result<Zod.infer<TValueModel>, Zod.infer<TErrorModel>> {
  return Zod.discriminatedUnion('ok', [
    Zod.object({
      ok: Zod.literal(true),
      value: valueModel,
    }),
    Zod.object({
      ok: Zod.literal(false),
      error: errorModel ?? Zod.unknown(),
    }),
  ]) as any
}
