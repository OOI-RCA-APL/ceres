import {
  QueryClient,
  QueryKey,
  Register,
  UseQueryDefinedReturnType,
  UseQueryOptions,
  UseQueryReturnType,
  useQuery as useQueryBase,
} from '@tanstack/vue-query'
import { DeepMaybeRef, useMounted } from '@vueuse/core'
import { defineStore } from 'pinia'
import { v7 } from 'uuid'
import { reactive, watchEffect, onUnmounted, DeepReadonly, MaybeRef } from 'vue'
import { ZodAny, ZodError, ZodTypeAny } from 'zod'

import { ErrorInfo, Failure } from '@/errors'

export type RequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type RequestOptions<TParseModel extends ZodTypeAny = ZodAny> = {
  query?: Record<string, unknown> | null
  data?: Record<string, unknown> | unknown[] | null
  init?: RequestInit
  parse?: TParseModel
}

const defaultRequestInit: RequestInit = {
  credentials: 'include',
  redirect: 'follow',
  headers: {
    'Content-Type': 'application/json',
  },
}

async function request<TParseModel extends ZodTypeAny = ZodAny>(
  method: RequestMethod,
  path: string,
  { query, data, parse, init }: RequestOptions<TParseModel> = {}
): Promise<Zod.infer<TParseModel>> {
  const response = await fetch(query != null ? path + createQueryParameters(query) : path, {
    ...defaultRequestInit,
    ...init,
    method,
    body: data != null ? JSON.stringify(data) : undefined,
  })

  let result: unknown
  try {
    result = await response.json()
  } catch (error) {
    console.error(`${method} ${path}: ${response.status} (non-json-response-error)`)
    throw new Failure({
      __error__: true,
      type: 'non-json-response-error',
      message: String(error),
    })
  }

  if (response.status >= 400) {
    console.error(`${method} ${path}: ${response.status}`)
    throw new Failure(result as ErrorInfo)
  }

  if (parse == null) {
    return result
  }

  try {
    return await parse.parseAsync(result)
  } catch (error) {
    if (error instanceof ZodError) {
      console.error(
        `${method} ${path}: ${response.status} (response-parse-error) ${JSON.stringify(
          error.errors
        )}`
      )
      throw new Failure({
        __error__: true,
        type: 'response-parse-error',
        issues: error.errors,
      })
    } else {
      throw error
    }
  }
}

async function get<TParseModel extends ZodTypeAny = ZodAny>(
  path: string,
  options?: Omit<RequestOptions<TParseModel>, 'data'>
) {
  return request('GET', path, options)
}

async function post<TParseModel extends ZodTypeAny = ZodAny>(
  path: string,
  options?: RequestOptions<TParseModel>
) {
  return request('POST', path, options)
}

async function put<TParseModel extends ZodTypeAny = ZodAny>(
  path: string,
  options?: RequestOptions<TParseModel>
) {
  return request('PUT', path, options)
}

async function patch<TParseModel extends ZodTypeAny = ZodAny>(
  path: string,
  options?: RequestOptions<TParseModel>
) {
  return request('PATCH', path, options)
}

async function del<TParseModel extends ZodTypeAny = ZodAny>(
  path: string,
  options?: RequestOptions<TParseModel>
) {
  return request('DELETE', path, options)
}

function getWebSocketURI(relative: string) {
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
    if (process.env.DEVELOPMENT_CERES_API_PORT != null) {
      port = ':' + process.env.DEVELOPMENT_CERES_API_PORT
    } else {
      port = ''
    }
  }

  return `${protocol}://${hostname}${port}${relative}`
}

export type StreamInput = DeepReadonly<{
  id?: string
  path: string
  query?: Record<any, any> | null
}>

export type Stream = StreamInput & { id: string }

export type StreamOptions = Readonly<{
  disable?: boolean
}>

export type UseStreamOptions<TParseModel extends ZodTypeAny> = DeepReadonly<{
  stream: MaybeRef<StreamInput | StreamInput[]>
  disable?: boolean
  parse: TParseModel
  onReceive?: (message: Zod.infer<TParseModel>, stream: Stream) => unknown
  onDisconnect?: (option: StreamInput) => unknown
}>

type StreamEntry = {
  stream: Stream
  socket: WebSocket | null
}

function useStream<TParseModel extends ZodTypeAny>(
  inputOptions: DeepReadonly<DeepMaybeRef<UseStreamOptions<TParseModel>>>
) {
  const ids = [] as string[]
  function getId(index: number) {
    while (ids.length <= index) {
      ids.push(v7())
    }
    return ids[index]
  }

  const mounted = $(useMounted())

  const options = $computed(() => {
    const temporary = reactive(inputOptions)
    return reactive({
      ...temporary,
      stream: (Array.isArray(temporary.stream) ? temporary.stream : [temporary.stream])
        .map((current) => (typeof current === 'string' ? { stream: current } : current))
        .map((current, i) => ({ id: current.id ?? getId(i), ...current })) as Stream[],
    })
  })

  let entries = $ref<Record<string, StreamEntry>>({})

  function onClose(stream: Stream) {
    const entry = entries[stream.id]
    if (entry == null) {
      return
    }

    entry.socket?.close()
    entry.socket = null
    if (mounted && !options.disable) {
      setTimeout(() => {
        if (
          !options.disable &&
          mounted &&
          entry.socket == null &&
          entries[stream.id] != null &&
          entries[stream.id].socket == null &&
          JSON.stringify(entries[stream.id].stream) === JSON.stringify(stream)
        ) {
          entries[stream.id].socket = createSocket(
            entry.stream,
            options as UseStreamOptions<TParseModel>,
            onClose
          )
        }
      }, 1000)
    }
  }

  function clear() {
    for (const entry of Object.values(entries)) {
      if (entry.socket != null && entry.socket.readyState === WebSocket.OPEN) {
        entry.socket.close()
        entry.socket = null
      }
    }

    entries = {}
  }

  window.addEventListener('unload', clear)

  onUnmounted(() => {
    window.removeEventListener('unload', clear)
    clear()
  })

  watchEffect(() => {
    for (const stream of options.stream) {
      const entry = entries[stream.id]

      if (
        entry != null &&
        (options.disable || JSON.stringify(stream ?? null) !== JSON.stringify(entry.stream))
      ) {
        entry.socket?.close()
        delete entries[stream.id]
      }

      const socket = options.disable
        ? null
        : createSocket(stream, options as UseStreamOptions<TParseModel>, onClose)

      entries[stream.id] = { stream, socket }
    }
  })
}

function createSocket<TParseModel extends ZodTypeAny>(
  stream: Stream,
  options: UseStreamOptions<TParseModel>,
  onClose: (stream: Stream) => unknown
) {
  const url = getWebSocketURI(stream.path) + createQueryParameters(stream.query ?? {})
  const socket = new WebSocket(url)
  socket.addEventListener('open', () => {
    console.log(`Connected to '${url}'.`)
  })

  socket.addEventListener('message', (event) => {
    let data
    try {
      data = JSON.parse(event.data)
    } catch {
      console.log(`Invalid JSON message from '${url}': '${event.data}'`)
      return
    }

    const result = options.parse.safeParse(data)
    if (result.success) {
      if (options.onReceive != null) {
        options.onReceive(result.data, stream)
      }
    } else {
      console.error(url, options.parse, data, result.error)
    }
  })

  socket.addEventListener('error', (event) => {
    console.log(`Error on '${url}': ${event.type}`)
  })

  socket.addEventListener('close', () => {
    console.log(`Disconnected from '${url}'.`)
    try {
      onClose(stream)
    } finally {
      if (options.onDisconnect != null) {
        options.onDisconnect(stream)
      }
    }
  })

  return socket
}

export const useClient = defineStore('client', () => {
  return {
    request,
    get,
    post,
    put,
    patch,
    delete: del,
    useQuery,
    useStream,
  }
})

function createQueryParameters(values: Record<string, unknown>): string {
  const keys = Object.keys(values)
  if (keys.length === 0) {
    return ''
  }

  function stringify(value: unknown): string {
    if (value == undefined) {
      return ''
    }

    if (typeof value === 'object') {
      if (typeof value?.valueOf() === 'string') {
        value = value.valueOf()
      } else {
        value = JSON.stringify(value)
      }
    }

    return String(value)
  }

  const result = new URLSearchParams()
  for (const key of keys) {
    const value = values[key]
    if (Array.isArray(value)) {
      for (const element of value) {
        if (element != undefined) {
          result.append(key, stringify(element))
        }
      }

      continue
    }

    if (value !== undefined) {
      result.append(key, stringify(value))
    }
  }

  const text = result.toString()
  if (text !== '') {
    return '?' + text
  }

  return text
}

type NonUndefinedGuard<T> = T extends undefined ? never : T
type DefaultError = Register extends {
  defaultError: infer TError
}
  ? TError
  : Error

type UndefinedInitialQueryOptions<
  TQueryFnData = unknown,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
> = UseQueryOptions<TQueryFnData, TError, TData, TQueryFnData, TQueryKey> & {
  initialData?: undefined
}
type DefinedInitialQueryOptions<
  TQueryFnData = unknown,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
> = UseQueryOptions<TQueryFnData, TError, TData, TQueryFnData, TQueryKey> & {
  initialData: NonUndefinedGuard<TQueryFnData> | (() => NonUndefinedGuard<TQueryFnData>)
}

// @ts-ignore
declare function useQuery<
  TQueryFnData = unknown,
  TError = Failure,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(
  options: UndefinedInitialQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
  queryClient?: QueryClient
): UseQueryReturnType<TData, TError>
// @ts-ignore
declare function useQuery<
  TQueryFnData = unknown,
  TError = Failure,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(
  options: DefinedInitialQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
  queryClient?: QueryClient
): UseQueryDefinedReturnType<TData, TError>
// @ts-ignore
declare function useQuery<
  TQueryFnData = unknown,
  TError = Failure,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey
>(
  options: UseQueryOptions<TQueryFnData, TError, TData, TQueryFnData, TQueryKey>,
  queryClient?: QueryClient
): UseQueryReturnType<TData, TError>

// @ts-ignore
export const useQuery = useQueryBase
