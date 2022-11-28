import Zod, { ZodTypeAny } from 'zod'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = Zod.object({
  id: Zod.string(),
  connection_id: Zod.string(),
  timestamp: Zod.string(),
  direction: MessageDirectionModel,
  content: Zod.string(),
})

export type AlertLevel = Zod.infer<typeof AlertLevelModel>
export const AlertLevelModel = Zod.enum(['info', 'warning', 'error'])

export type Alert = Zod.infer<typeof AlertModel>
export const AlertModel = Zod.object({
  id: Zod.string(),
  origin_id: Zod.string(),
  timestamp: Zod.string(),
  level: AlertLevelModel,
  kind: Zod.string(),
  info: Zod.record(Zod.string(), Zod.unknown()).default(() => ({})),
})

export type ComponentKind = Zod.infer<typeof ComponentKindModel>
export const ComponentKindModel = Zod.enum(['connection', 'driver', 'notifier'])

export const ComponentConfigModel = Zod.object({
  kind: ComponentKindModel,
  name: NameStrModel,
  component: Zod.string(),
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
  path: Zod.string(),
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

export type UnitInfo = Zod.infer<typeof UnitInfoModel>
export const UnitInfoModel = Zod.object({
  id: Zod.string(),
  config: UnitConfigModel,
})

export type ComponentInfo = Zod.infer<typeof ComponentInfoModel>
export const ComponentInfoModel = Zod.object({
  id: Zod.string(),
  config: ComponentConfigModel,
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
