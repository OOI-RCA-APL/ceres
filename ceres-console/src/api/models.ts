import Zod, { ZodTypeAny } from 'zod'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = Zod.object({
  id: Zod.string(),
  source: Zod.string(),
  timestamp: Zod.string(),
  direction: MessageDirectionModel,
  content: Zod.string(),
})

export type AlertLevel = Zod.infer<typeof AlertLevelModel>
export const AlertLevelModel = Zod.enum(['debug', 'info', 'warning', 'error', 'critical'])

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = Zod.object({
  id: Zod.string(),
  source: Zod.string(),
  timestamp: Zod.string(),
  level: AlertLevelModel,
  kind: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type ComponentRole = Zod.infer<typeof ComponentRoleModel>
export const ComponentRoleModel = Zod.enum(['connection', 'dispatcher', 'notifier'])

export type ComponentConfig = Zod.infer<typeof ComponentConfigModel>
export const ComponentConfigModel = Zod.object({
  name: NameStrModel,
  class: Zod.string(),
  parameters: Zod.record(NameStrModel, Zod.unknown()).default(() => ({})),
  references: Zod.record(NameStrModel, NameStrModel).default(() => ({})),
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

export type UnitConfig = Zod.infer<typeof UnitConfigModel>
export const UnitConfigModel = Zod.object({
  name: NameStrModel,
  components: Zod.array(ComponentConfigModel).default(() => []),
})

export type UserConfig = Zod.infer<typeof UserConfigModel>
export const UserConfigModel = Zod.object({
  username: NameStrModel,
  email: EmailStrModel,
  meta: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type Config = Zod.infer<typeof ConfigModel>
export const ConfigModel = Zod.object({
  server: ServerConfigModel,
  database: DatabaseConfigModel,
  users: Zod.array(UserConfigModel).default(() => []),
  units: Zod.array(UnitConfigModel).default(() => []),
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

export type LayoutNode = Zod.infer<typeof LayoutNodeModel>
export const LayoutNodeModel = Zod.union([LayoutDisplayModel, LayoutColumnModel, LayoutRowModel])

export type Layout = Zod.infer<typeof LayoutModel>
export const LayoutModel = Zod.object({
  body: LayoutNodeModel,
})

export type ComponentInfo = Zod.infer<typeof ComponentInfoModel>
export const ComponentInfoModel = Zod.object({
  id: Zod.string(),
  name: Zod.string(),
  address: Zod.string(),
  config: ComponentConfigModel,
  roles: Zod.array(ComponentRoleModel),
  layout: LayoutModel.nullable(),
})

export type UnitInfo = Zod.infer<typeof UnitInfoModel>
export const UnitInfoModel = Zod.object({
  name: Zod.string(),
  config: UnitConfigModel,
  components: Zod.array(ComponentInfoModel),
})

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
