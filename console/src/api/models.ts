import { Address } from '@/address'
import moment from 'moment'
import Zod, { ZodTypeAny } from 'zod'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

const DateTimeModel = Zod.string().refine((value) => moment.utc(value).isValid())
const TimeDeltaModel = Zod.string().refine((value) => moment.duration(value).isValid())

export type Connectivity = Zod.infer<typeof ConnectivityModel>
export const ConnectivityModel = Zod.enum(['disconnected', 'connecting', 'connected'])

export type Status = Zod.infer<typeof StatusModel>
export const StatusModel = Zod.object({
  address: Zod.string().transform(Address.parse),
  running: Zod.boolean(),
  enabled: Zod.boolean().nullable().default(null),
  connectivity: ConnectivityModel.nullable().default(null),
})

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
export const ComponentRoleModel = Zod.enum(['connection', 'interface'])

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

export type ConsoleConfig = Zod.infer<typeof ConsoleConfigModel>
export const ConsoleConfigModel = Zod.object({
  title: Zod.string().nullable().default(null),
  icon: Zod.string().nullable().default(null),
  favicon: Zod.string().nullable().default(null),
  dashboard: Zod.string().transform(Address.parse).nullable().default(null),
})

export type ServerConfig = Zod.infer<typeof ServerConfigModel>
export const ServerConfigModel = Zod.object({
  port: Zod.number().nullable().default(null),
  console: ConsoleConfigModel.nullable().default(null),
})

export type Config = Zod.infer<typeof ConfigModel>
export const ConfigModel = Zod.object({
  name: NameStrModel,
  class: Zod.string(),
  components: Zod.array(ComponentConfigModel),
  server: ServerConfigModel,
  database: DatabaseConfigModel,
})

export type ButtonElement = Zod.infer<typeof ButtonElementModel>
export const ButtonElementModel = Zod.object({
  type: Zod.literal('button'),
  title: Zod.string(),
  address: Zod.string().transform(Address.parse),
  action: Zod.string(),
  color: Zod.string().optional().nullable(),
})

export type Justify = Zod.infer<typeof JustifyModel>
export const JustifyModel = Zod.enum(['start', 'center', 'end', 'space-between', 'space-evenly'])

export type Align = Zod.infer<typeof AlignModel>
export const AlignModel = Zod.enum(['start', 'center', 'end'])

export type Sizing = Zod.infer<typeof SizingModel>
export const SizingModel = Zod.enum(['shrink', 'grow'])

export type AtomicValue = Zod.infer<typeof AtomicValueModel>
export const AtomicValueModel = Zod.union([Zod.boolean(), Zod.number(), Zod.string()])

export type ColorStop = Zod.infer<typeof ColorStopModel>
export const ColorStopModel = Zod.object({
  value: Zod.number(),
  color: Zod.string(),
})

export type StateElementOption = Zod.infer<typeof StateElementOptionModel>
export const StateElementOptionModel = Zod.object({
  value: AtomicValueModel,
  label: Zod.string(),
  color: Zod.string(),
  icon: Zod.string().nullable().default(null),
  description: Zod.string().nullable().default(null),
})

type BoxElement = {
  sizing: Sizing
  justify: Justify
  align: Align
  children: Element[]
}

const BoxModelElement = {
  sizing: SizingModel.default('grow'),
  justify: JustifyModel.default('start'),
  align: AlignModel.default('start'),
  children: Zod.lazy(() => Zod.array(ElementModel)),
}

export type RowElement = {
  type: 'row'
} & BoxElement

export const RowElementModel = Zod.object({
  type: Zod.literal('row'),
  ...BoxModelElement,
}) as Zod.ZodType<RowElement>

export type ColumnElement = {
  type: 'column'
} & BoxElement

export const ColumnElementModel = Zod.object({
  type: Zod.literal('column'),
  ...BoxModelElement,
}) as Zod.ZodType<ColumnElement>

export type CarouselElement = {
  type: 'carousel'
  children: Element[]
  height?: number | string | null
}

export const CarouselElementModel = Zod.object({
  type: Zod.literal('carousel'),
  height: Zod.union([Zod.string(), Zod.number()]).optional().nullable(),
  children: Zod.lazy(() => Zod.array(ElementModel)),
}) as Zod.ZodType<CarouselElement>

export type ValueElement = Zod.infer<typeof ValueElementModel>
export const ValueElementModel = Zod.object({
  type: Zod.literal('value'),
  value: AtomicValueModel,
  unit: Zod.string().nullable().default(null),
  color: Zod.string().nullable().default(null),
})

export type StateElement = Zod.infer<typeof StateElementModel>
export const StateElementModel = Zod.object({
  type: Zod.literal('state'),
  value: AtomicValueModel,
  options: Zod.array(StateElementOptionModel),
})

export type GaugeElement = Zod.infer<typeof GaugeElementModel>
export const GaugeElementModel = Zod.object({
  type: Zod.literal('gauge'),
  value: Zod.number(),
  unit: Zod.string().nullable().default(null),
  min: Zod.number(),
  max: Zod.number(),
  color: Zod.union([Zod.array(ColorStopModel), Zod.string()])
    .nullable()
    .default(null),
})

export type ChartElement = Zod.infer<typeof ChartElementModel>
export const ChartElementModel = Zod.object({
  type: Zod.literal('chart'),
  value: Zod.record(Zod.string(), Zod.any()),
  height: Zod.number(),
})

export type RenderElement = Zod.infer<typeof RenderElementModel>
export const RenderElementModel = Zod.object({
  type: Zod.literal('display'),
  address: Zod.string().transform(Address.parse),
  query: Zod.string(),
})

export type DisplayElement = Zod.infer<typeof DisplayElementModel>
export const DisplayElementModel = Zod.object({
  type: Zod.literal('display'),
  title: Zod.string(),
  address: Zod.string().transform(Address.parse),
  query: Zod.string(),
})

export function createColorStops(
  value: number,
  color: ColorStop[] | string | undefined | null,
  darkMode: boolean
) {
  if (color == null) {
    color = darkMode ? 'white' : 'black'
  }

  if (typeof color === 'string') {
    return [
      [0, color],
      [value, color],
    ]
  }

  const max = Math.max(...color.map((entry) => entry.value))
  return color.map((stop) => [stop.value / max, stop.color])
}

export type Element =
  | ButtonElement
  | RowElement
  | ColumnElement
  | CarouselElement
  | ValueElement
  | StateElement
  | GaugeElement
  | ChartElement
  | DisplayElement

export const ElementModel: Zod.ZodType<Element> = Zod.discriminatedUnion('type', [
  ButtonElementModel,
  RowElementModel,
  ColumnElementModel,
  CarouselElementModel,
  ValueElementModel,
  StateElementModel,
  GaugeElementModel,
  ChartElementModel,
  DisplayElementModel,
] as any)

export type ElementType = Element['type']

export type ProcedureType = Zod.infer<typeof ProcedureTypeModel>
export const ProcedureTypeModel = Zod.enum(['query', 'action'])

export type ProcedureArgsInfo = Zod.infer<typeof ProcedureArgumentsInfoModel>
export const ProcedureArgumentsInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
  required: Zod.boolean(),
})

export type ProcedureOutputInfo = Zod.infer<typeof ProcedureOutputInfoModel>
export const ProcedureOutputInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
})

const BaseProcedureInfoModel = Zod.object({
  name: Zod.string(),
  type: ProcedureTypeModel,
  live: Zod.boolean(),
  arguments: ProcedureArgumentsInfoModel,
  output: ProcedureOutputInfoModel,
})

export type QueryInfo = Zod.infer<typeof QueryInfoModel>
export const QueryInfoModel = BaseProcedureInfoModel.extend({
  type: Zod.literal('query'),
})

export type ActionInfo = Zod.infer<typeof ActionInfoModel>
export const ActionInfoModel = BaseProcedureInfoModel.extend({
  type: Zod.literal('action'),
})

export type ProcedureInfo = Zod.infer<typeof ProcedureInfoModel>
export const ProcedureInfoModel = Zod.discriminatedUnion('type', [QueryInfoModel, ActionInfoModel])

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
