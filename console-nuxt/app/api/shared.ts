import * as z from 'zod'

import type { Alert } from '@/api/alerts'
import type { LogEntry } from '@/api/logs'
import type { Message } from '@/api/messages'
import type { Particle } from '@/api/particles'
import { duration, utc } from '@/time'

export const NameStrModel = z.string().regex(/[a-zA-Z\-_][a-zA-Z0-9\-_]*/)
export const EmailStrModel = z.string().regex(/.+@.+/)
export const NonEmptyStrModel = z.string().regex(/.+/)

export const DateTimeModel = z.string().refine((value) => utc(value).isValid())
export const TimeDeltaModel = z.string().refine((value) => duration(value).isValid())

export type Record = Message | Alert | LogEntry | Particle

export type Connectivity = z.infer<typeof ConnectivityModel>
export const ConnectivityModel = z.enum(['disconnected', 'connecting', 'connected'])

export type Level = z.infer<typeof LevelModel>
export const LevelModel = z.enum(['debug', 'info', 'warning', 'error', 'critical'])

export type ErrorObject = z.infer<typeof ErrorModel>
export const ErrorModel = z.looseObject({
  __error__: z.literal(true),
  type: z.string(),
})

export function isOk(value: unknown): boolean {
  return !isError(value)
}

export function isError(value: unknown): value is ErrorObject {
  if (value == null || typeof value !== 'object') {
    return false
  }

  return '__error__' in value && Boolean(value.__error__)
}

export type Result<T> = T | ErrorObject
export function ResultModel<T extends z.ZodType>(ok: T) {
  return z.union([ok, ErrorModel])
}

export type AnyResult = Result<any>
export const AnyResultModel = ResultModel(z.any())
