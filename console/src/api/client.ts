import { ErrorInfo, Failure } from '@/errors'
import {
  QueryClient,
  QueryKey,
  Register,
  UseQueryDefinedReturnType,
  UseQueryOptions,
  UseQueryReturnType,
  useQuery as useQueryBase,
} from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref, watchEffect } from 'vue'
import { ZodAny, ZodError, ZodTypeAny } from 'zod'

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
      console.error(`${method} ${path}: ${response.status} (response-parse-error)`)
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
    port = ':' + process.env.DEVELOPMENT_CERES_API_PORT ?? ''
  }

  return `${protocol}://${hostname}${port}${relative}`
}

export type StreamOptions = {
  query?: MaybeRef<Record<string, unknown>> | null
  disable?: MaybeRef<boolean>
}

function useStream<TParseModel extends ZodTypeAny>(
  path: MaybeRef<string>,
  parse: TParseModel,
  onReceive: (message: Zod.infer<TParseModel>) => unknown,
  options?: MaybeRef<StreamOptions>
) {
  const inputOptions = computed(() => unref(options) ?? {})
  const inputUrl = computed(() => {
    const base = getWebSocketURI(unref(path))
    return base + createQueryParameters(unref(inputOptions.value.query ?? {}))
  })

  function createSocket(activeUrl: string, onDisconnect: () => unknown) {
    const socket = new WebSocket(activeUrl)
    socket.addEventListener('open', () => {
      console.log(`connected to '${activeUrl}'`)
    })

    socket.addEventListener('message', (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        console.log(`invalid JSON message from '${activeUrl}': '${event.data}'`)
        return
      }

      const result = parse.safeParse(data)
      if (result.success) {
        onReceive(result.data)
      } else {
        console.error(inputUrl, parse, data, result.error)
      }
    })

    socket.addEventListener('error', (event) => {
      console.log(`error on '${activeUrl}': ${event.type}`)
    })

    socket.addEventListener('close', () => {
      console.log(`disconnected from '${activeUrl}'`)
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
          socket = createSocket(inputUrl.value, onDisconnect)
        }
      }, 3000)
    }

    let socket = inputOptions.value.disable ? null : createSocket(inputUrl.value, onDisconnect)

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

  const result = new URLSearchParams()
  for (const key of keys) {
    let value = values[key]
    if (Array.isArray(value)) {
      for (const element of value) {
        if (element != undefined) {
          result.append(key, String(element.valueOf()))
        }
      }

      continue
    }

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
