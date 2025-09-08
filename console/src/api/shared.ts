import moment from 'moment'
import Zod, { ZodTypeAny } from 'zod'

import type { Alert } from '@/api/alerts'
import type { LogEntry } from '@/api/logs'
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

export type ErrorObject = Zod.infer<typeof ErrorModel>
export const ErrorModel = Zod.object({
  __error__: Zod.literal(true),
  type: Zod.string(),
}).passthrough()

export function isOk(obj: any): boolean {
  return !isError(obj)
}

export function isError(obj: any): obj is ErrorObject {
  return '__error__' in obj && Boolean(obj.__error__)
}

export type Result<T> = T | ErrorObject
export function ResultModel<T extends ZodTypeAny>(ok: T) {
  return Zod.union([ok, ErrorModel])
}

export type AnyResult = Result<any>
export const AnyResultModel = ResultModel(Zod.any())
