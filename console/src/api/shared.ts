import { Address } from '@/address'
import type { Alert } from '@/api/alerts'
import type { LogEntry } from '@/api/log-entries'
import type { Message } from '@/api/messages'
import { MaybeRef } from '@vueuse/core'
import moment from 'moment'
import { computed, unref, watchEffect } from 'vue'
import Zod, { ZodTypeAny } from 'zod'

export const NameStrModel = Zod.string().regex(/[a-zA-Z\-\_][a-zA-Z0-9\-\_]*/)
export const EmailStrModel = Zod.string().regex(/.+@.+/)
export const NonEmptyStrModel = Zod.string().regex(/.+/)

export const DateTimeModel = Zod.string().refine((value) => moment.utc(value).isValid())
export const TimeDeltaModel = Zod.string().refine((value) => moment.duration(value).isValid())

export type Item = Message | Alert | LogEntry

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

export function getWebSocketURI(relative: string) {
  const protocol = window.location.protocol.startsWith('https') ? 'wss' : 'ws'
  const hostname = window.location.hostname
  let port: string
  if (process.env.NODE_ENV === 'production') {
    if (window.location.port !== '') {
      port = ':' + window.location.port
    } else {
      port = ''
    }
  } else {
    port = ':' + process.env.DEVELOPMENT_CERES_API_PORT ?? ''
  }

  return `${protocol}://${hostname}${port}${relative}`
}

export type ItemStreamFilter = {
  address?: Address
  search?: string
}

const defaultRequestOptions = {
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
  },
} as const

export type ErrorInfo = {
  __error__: true
  type: string
}

export function isError(value: unknown): value is ErrorInfo {
  return value != null && typeof value === 'object' && (value as any)['__error__'] === true
}

export function isOk<T>(value: T | ErrorInfo): value is T {
  return !isError(value)
}

export async function get<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  options?: RequestInit
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    ...options,
  })
  if (response.status >= 400) {
    throw Error(`GET ${url} ${await response.text()}`)
  }

  const json = await response.json()
  return await model.parseAsync(json)
}

export async function getOrNull<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  options?: RequestInit
): Promise<Zod.infer<TModel> | null> {
  try {
    return await get(url, model, options)
  } catch {
    return null
  }
}

export async function post<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  data?: unknown,
  options?: RequestInit
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    method: 'POST',
    body: data != null ? JSON.stringify(data) : undefined,
    ...options,
  })

  if (response.status >= 400) {
    throw Error(`POST ${url} ${await response.text()}`)
  }

  const json = await response.json()
  return await model.parseAsync(json)
}

export async function postOrError<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  data?: unknown,
  options?: RequestInit
): Promise<Zod.infer<TModel> | ErrorInfo> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    method: 'POST',
    body: data != null ? JSON.stringify(data) : undefined,
    ...options,
  })

  const json = await response.json()
  if (isError(json)) {
    return json
  }

  return await model.parseAsync(json)
}

export async function patch<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  data?: unknown,
  options?: RequestInit
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    body: data != null ? JSON.stringify(data) : undefined,
    method: 'PATCH',
    ...options,
  })

  if (response.status >= 400) {
    throw Error(`PATCH ${url} ${await response.text()}`)
  }

  const json = await response.json()
  return await model.parseAsync(json)
}

export async function patchOrError<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  data?: unknown,
  options?: RequestInit
): Promise<Zod.infer<TModel> | ErrorInfo> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    body: data != null ? JSON.stringify(data) : undefined,
    method: 'PATCH',
    ...options,
  })

  const json = await response.json()
  if (isError(json)) {
    return json
  }

  return await model.parseAsync(json)
}

export async function deleteOrError<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  options?: RequestInit
): Promise<Zod.infer<TModel> | ErrorInfo> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    method: 'DELETE',
    ...options,
  })

  const json = await response.json()
  if (isError(json)) {
    return json
  }

  return await model.parseAsync(json)
}

export function createQueryParams(values: Record<string, unknown>): string {
  const result = new URLSearchParams()
  for (const key of Object.keys(values)) {
    let value = values[key]
    if (typeof value === 'object') {
      if (typeof value?.valueOf() === 'string') {
        value = value.valueOf()
      } else {
        value = JSON.stringify(value)
      }
    }

    if (value !== undefined) {
      result.append(key, String(value))
    }
  }

  const text = result.toString()
  if (text !== '') {
    return '?' + text
  }

  return text
}

export type UseStreamOptions = {
  disable?: boolean
}

export function useStream<TModel extends ZodTypeAny, TContext>(
  url: MaybeRef<string | URL>,
  context: MaybeRef<TContext>,
  model: TModel,
  onMessage: (message: Zod.infer<TModel>, context: TContext) => unknown,
  options: MaybeRef<UseStreamOptions> = {}
) {
  const urlRef = computed(() => unref(url))
  const optionsRef = computed(() => unref(options))
  function createSocket(url: string | URL, onDisconnect: () => unknown) {
    const socket = new WebSocket(urlRef.value)
    socket.addEventListener('open', () => {
      console.log(`connected to '${url}'`)
    })

    socket.addEventListener('message', (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        console.log(`invalid JSON message from '${url}': '${event.data}'`)
        return
      }

      const result = model.safeParse(data)
      if (result.success) {
        onMessage(result.data, unref(context))
      } else {
        console.error(url, model, data, result.error)
      }
    })

    socket.addEventListener('error', (event) => {
      console.log(`error on '${url}': ${event.type}`)
    })

    socket.addEventListener('close', () => {
      console.log(`disconnected from '${url}'`)
      onDisconnect()
    })

    return socket
  }

  watchEffect((onCleanup) => {
    let mounted = true

    function onDisconnect() {
      socket?.close()
      setTimeout(() => {
        if (mounted) {
          socket = createSocket(urlRef.value, onDisconnect)
        }
      }, 3000)
    }

    let socket = optionsRef.value.disable ? null : createSocket(urlRef.value, onDisconnect)

    function onUnload() {
      if (socket == null) {
        return
      }

      if (socket.readyState == WebSocket.OPEN) {
        socket.close()
      }
    }

    window.addEventListener('unload', onUnload)

    onCleanup(() => {
      mounted = false
      window.removeEventListener('unload', onUnload)
      if (socket != null) {
        socket.close()
      }
    })
  })
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
