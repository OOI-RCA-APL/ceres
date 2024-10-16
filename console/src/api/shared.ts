import moment from 'moment'
import Zod, { ZodTypeAny } from 'zod'

import type { Alert } from '@/api/alerts'
import type { LogEntry } from '@/api/log-entries'
import type { Message } from '@/api/messages'
import type { Particle } from '@/api/particles'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

export const DateTimeModel = Zod.string().refine((value) => moment.utc(value).isValid())
export const TimeDeltaModel = Zod.string().refine((value) => moment.duration(value).isValid())

export type Record = Message | Alert | LogEntry | Particle

export type Connectivity = Zod.infer<typeof ConnectivityModel>
export const ConnectivityModel = Zod.enum(['disconnected', 'connecting', 'connected'])

export type Level = Zod.infer<typeof LevelModel>
export const LevelModel = Zod.enum(['debug', 'info', 'warning', 'error', 'critical'])

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

export const BaseOkModel = Zod.object({
  ok: Zod.literal(true),
  value: Zod.unknown(),
})

export const BaseFailModel = Zod.object({
  ok: Zod.literal(false),
  error: Zod.unknown(),
})

export const BaseResultModel = Zod.discriminatedUnion('ok', [BaseOkModel, BaseFailModel])

export function createResultType<TValueModel extends ZodTypeAny, TErrorModel extends ZodTypeAny>(
  valueModel: TValueModel,
  errorModel: TErrorModel
) {
  const okModel = BaseOkModel.extend({
    value: valueModel,
  })

  const failModel = BaseFailModel.extend({
    error: errorModel,
  })

  return Zod.discriminatedUnion('ok', [okModel, failModel])
}
