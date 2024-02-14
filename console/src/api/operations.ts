import { Address } from '@/address'
import {
  Alert,
  AlertModel,
  ComponentInfo,
  ComponentInfoModel,
  Config,
  ConfigModel,
  ConsoleConfig,
  ConsoleConfigModel,
  ElementModel,
  Identity,
  IdentityModel,
  LogEntry,
  LogEntryModel,
  Message,
  MessageModel,
  ProcedureInfo,
  ProcedureInfoModel,
  Statistics,
  StatisticsModel,
  Status,
  StatusModel,
  User,
  UserModel,
} from '@/api/models'
import { computed, isRef, unref, watchEffect } from 'vue'
import { MaybeRef } from 'vue-query/lib/vue/types'
import Zod, { ZodTypeAny } from 'zod'
export * from 'vue-query'

export async function postReload(): Promise<Config | ErrorInfo> {
  return await postOrError('/api/reload', ConfigModel)
}

function getAuthorizationCookieType() {
  if (location.protocol.startsWith('https')) {
    return 'secure'
  }

  return 'insecure'
}

export async function postLogin(data: { username: string; password: string }): Promise<Identity> {
  return await post('/api/auth/login', IdentityModel, {
    ...data,
    cookie: getAuthorizationCookieType(),
  })
}

export async function postRefresh(): Promise<Identity> {
  return await post('/api/auth/refresh', IdentityModel, { cookie: getAuthorizationCookieType() })
}

export async function postLogout(): Promise<Identity> {
  return await post('/api/auth/logout', IdentityModel)
}

export async function postChangePassword(data: { oldPassword: string; newPassword: string }) {
  return await post('/api/auth/change-password', UserModel, data)
}

export async function patchUser(id: string, data: { password: string }) {
  return await patch(`/api/users/${id}`, UserModel, data)
}

export async function getMe(): Promise<Identity> {
  return await get('/api/auth/me', IdentityModel)
}

export async function getConfig(): Promise<Config> {
  return await get('/api/config', ConfigModel)
}

export async function getConsoleConfig(): Promise<ConsoleConfig> {
  return await get('/api/config/console', ConsoleConfigModel)
}

export async function getComponent(address: Address): Promise<ComponentInfo | null> {
  return await getOrNull(`/api/components/${address}`, ComponentInfoModel)
}

export async function getComponentProcedure(
  address: Address,
  procedure: string
): Promise<ProcedureInfo | null> {
  return await getOrNull(`/api/components/${address}/procedures/${procedure}`, ProcedureInfoModel)
}

export async function getUser(id: string): Promise<User | null> {
  return await getOrNull(`/api/users/${id}`, UserModel)
}

export async function getUsers(): Promise<User[]> {
  return await get(`/api/users`, Zod.array(UserModel))
}

export async function deleteUser(id: string): Promise<User | ErrorInfo> {
  return await deleteOrError(`/api/users/${id}`, UserModel)
}

export async function createUser(data: Omit<User, 'id'>): Promise<User | ErrorInfo> {
  return await postOrError(`/api/users`, UserModel, data)
}

export async function updateUser(id: string, data: Partial<User>): Promise<User | ErrorInfo> {
  return await patchOrError(`/api/users/${id}`, UserModel, data)
}

export async function getMessages(params: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<Message[]> {
  return await get(`/api/messages${createQueryParams(params)}`, Zod.array(MessageModel))
}

export async function getAlerts(params: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<Alert[]> {
  return await get(`/api/alerts${createQueryParams(params)}`, Zod.array(AlertModel))
}

export async function getLogEntries(params: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<LogEntry[]> {
  return await get(`/api/log-entries${createQueryParams(params)}`, Zod.array(LogEntryModel))
}

export async function getStatistics(params: {
  within?: number
  after?: string
  before?: string
}): Promise<Statistics[]> {
  return await get(`/api/statistics${createQueryParams(params)}`, Zod.array(StatisticsModel))
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

export function useStatusesStream(
  params: MaybeRef<{
    address?: Address
  }>,
  onReceive: (message: Status[]) => unknown,
  options: MaybeRef<UseStreamOptions> = {}
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/statuses${createQueryParams(isRef(params) ? params.value : params)}`)
    ),
    params,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    Zod.array(StatusModel),
    onReceive,
    options
  )
}

type ItemStreamFilter = {
  address?: Address
  search?: string
}

export function useMessageStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (message: Message, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/messages${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    MessageModel,
    onReceive,
    options
  )
}

export function useAlertStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (alert: Alert, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/alerts${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    AlertModel,
    onReceive,
    options
  )
}

export function useLogEntryStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (entry: LogEntry, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/log-entries${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    LogEntryModel,
    onReceive,
    options
  )
}

const defaultRequestOptions = {
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json',
  },
} as const

async function get<TModel extends ZodTypeAny>(
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

async function getOrNull<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  options?: RequestInit
): Promise<Zod.infer<TModel> | null> {
  const response = await fetch(url, {
    ...defaultRequestOptions,
    ...options,
  })
  if (response.status >= 400) {
    return null
  }

  const json = await response.json()
  return await model.parseAsync(json)
}

async function post<TModel extends ZodTypeAny>(
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

type ErrorInfo = {
  __error__: true
  type: string
}

export function isError(value: unknown): value is ErrorInfo {
  return value != null && typeof value === 'object' && (value as any)['__error__'] === true
}

export function isOk<T>(value: T | ErrorInfo): value is T {
  return !isError(value)
}

async function postOrError<TModel extends ZodTypeAny>(
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

async function patch<TModel extends ZodTypeAny>(
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

async function patchOrError<TModel extends ZodTypeAny>(
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

async function deleteOrError<TModel extends ZodTypeAny>(
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

function createQueryParams(values: Record<string, unknown>): string {
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

type UseStreamOptions = {
  disable?: boolean
}

function useStream<TModel extends ZodTypeAny, TContext>(
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

export function useElementStream<TModel extends ZodTypeAny>(
  address: MaybeRef<Address>,
  query: MaybeRef<string>,
  args: MaybeRef<Record<string, unknown>>,
  onMessage: (message: Zod.infer<TModel>) => unknown
) {
  return useStream(
    computed(() =>
      getWebSocketURI(
        `/api/components/${unref(address)}/procedures/${unref(query)}/subscribe?arguments=` +
          encodeURIComponent(JSON.stringify(unref(args)))
      )
    ),
    args,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    ElementModel,
    onMessage
  )
}

const BaseOkModel = Zod.object({
  ok: Zod.literal(true),
  value: Zod.unknown(),
})

const BaseFailModel = Zod.object({
  ok: Zod.literal(false),
  error: Zod.unknown(),
})

const BaseResultModel = Zod.discriminatedUnion('ok', [BaseOkModel, BaseFailModel])

function createResultType<TValueModel extends ZodTypeAny, TErrorModel extends ZodTypeAny>(
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

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = createResultType(MessageModel, BaseFailModel)

export async function call(
  address: Address,
  procedure: string,
  args: MaybeRef<Record<string, any>> = {}
) {
  let url = `/api/components/${address}/procedures/${procedure}/call`
  if (Object.keys(args).length > 0) {
    url += `?arguments=${encodeURIComponent(JSON.stringify(unref(args)))}`
  }

  return await post(url, BaseResultModel)
}

export async function sendMessage(address: Address, data: string): Promise<SendMessageResult> {
  return await post(
    `/api/components/${address}/procedures/send-message/call`,
    SendMessageResultModel,
    { data }
  )
}

export type RenderResult = Zod.infer<typeof RenderResultModel>
const RenderResultModel = createResultType(ElementModel, BaseFailModel)

export async function render(address: Address): Promise<RenderResult> {
  return await get(`/api/components/${address}/procedures/render/call`, RenderResultModel)
}

export async function start(address: Address) {
  return await post('/api/start', Zod.any(), { address })
}

export async function stop(address: Address) {
  return await post('/api/stop', Zod.any(), { address })
}

export async function enable(address: Address) {
  return await post('/api/enable', Zod.any(), { address })
}

export async function disable(address: Address) {
  return await post('/api/disable', Zod.any(), { address })
}

export async function up(address: Address) {
  return await post('/api/up', Zod.any(), { address })
}

export async function down(address: Address) {
  return await post('/api/down', Zod.any(), { address })
}
