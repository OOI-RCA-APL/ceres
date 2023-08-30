import { Address } from '@/address'
import {
  Alert,
  AlertModel,
  ComponentConfig,
  ComponentInfo,
  ComponentInfoModel,
  Config,
  ConfigModel,
  LayoutModel,
  LevelStatistics,
  LogEntry,
  LogEntryModel,
  Message,
  MessageModel,
  Result,
  ResultModel,
  Statistics,
  StatisticsModel,
  Status,
  StatusModel,
} from '@/api/models'
import { DisplayInfoModel } from '@/display'
import { getter } from '@/getter'
import { useSettings } from '@/settings'
import { useIntervalFn } from '@vueuse/core'
import moment from 'moment'
import { defineStore } from 'pinia'
import { computed, isRef, ref, unref, watch, watchEffect } from 'vue'
import { useQuery } from 'vue-query'
import { MaybeRef } from 'vue-query/lib/vue/types'
import Zod, { ZodTypeAny } from 'zod'
export * from 'vue-query'

export async function reload(): Promise<Result<Config>> {
  return await post('/api/reload', ResultModel(ConfigModel) as any)
}

export async function getConfig(): Promise<Config> {
  return await get('/api/config', ConfigModel)
}

export async function getComponent(address: Address): Promise<ComponentInfo | null> {
  return await getOrNull(`/api/components/${address}`, ComponentInfoModel)
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
  onReceive: (message: Status[]) => unknown
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/statuses${createQueryParams(isRef(params) ? params.value : params)}`)
    ),
    params,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    Zod.array(StatusModel),
    onReceive
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

export const useConfig = defineStore('config', () => {
  const query = useQuery(['getConfig'], getConfig, { retry: false })

  const data = $computed(() => query.data.value as Config)
  const error = $computed(() => query.error)

  async function load() {
    await query.suspense()
  }

  function getComponent(address: Address): Config | ComponentConfig | null {
    if (address.isRoot) {
      return null
    }

    let current: Config | ComponentConfig | null = data
    for (const name of address.names) {
      if (current == null) {
        return null
      }

      current = current.components.find((component) => component.name === name) ?? null
    }

    return current
  }

  return {
    data: $$(data),
    error: $$(error),
    refetch: query.refetch,
    loading: $$(query.isLoading),
    load,
    getComponent,
  }
})

export const useStatistics = defineStore('statistics', () => {
  const settings = useSettings()
  const query = useQuery(
    ['statistics'],
    async () =>
      await getStatistics({
        within: settings.statisticsDuration.asSeconds(),
      })
  )

  const mapping = computed(() => {
    if (query.data.value == null) {
      return {}
    }

    return Object.fromEntries(
      query.data.value.map((statistics) => [statistics.address.toString(), statistics])
    )
  })

  const error = computed(() => query.error.value)

  async function load() {
    await query.suspense()
  }

  useIntervalFn(async () => {
    await query.refetch.value()
  }, moment.duration(15, 's').asMilliseconds())

  watch(
    computed(() => settings.statisticsDuration.asSeconds()),
    async () => {
      query.refetch.value()
    }
  )

  function get(address: Address): Statistics | null {
    return mapping.value[address.toString()] ?? null
  }

  function getAlertLevel(address: Address): LevelStatistics | null {
    const statistics = get(address)
    if (statistics == null) {
      return null
    }

    return statistics.alerts.levels[statistics.alerts.levels.length - 1] ?? null
  }

  return {
    get: getter(query.data, get),
    getAlertInfo: getter(query.data, getAlertLevel),
    error: $$(error),
    updatedAt: computed(() =>
      query.dataUpdatedAt.value ? moment(query.dataUpdatedAt.value) : null
    ),
    load,
  }
})

export const useStatuses = defineStore('statuses', () => {
  const statuses = ref<Record<string, Status>>({})

  useStatusesStream({}, (next) => {
    statuses.value = Object.fromEntries(next.map((status) => [status.address.toString(), status]))
  })

  function get(address: Address): Status | null {
    return statuses.value[address.toString()] ?? null
  }

  return {
    get: getter(statuses, get),
  }
})

async function get<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  options?: RequestInit
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url, options)
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
  const response = await fetch(url, options)
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
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: data != null ? JSON.stringify(data) : undefined,
    ...options,
  })

  if (response.status >= 400) {
    throw Error(`POST ${url} ${await response.text()}`)
  }

  const json = await response.json()
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

export function useDisplayStream<TModel extends ZodTypeAny>(
  address: MaybeRef<Address>,
  query: MaybeRef<string>,
  args: MaybeRef<Record<string, unknown>>,
  onDisplay: (message: Zod.infer<TModel>) => unknown
) {
  return useStream(
    computed(() =>
      getWebSocketURI(
        `/api/components/${unref(address)}/procedures/${unref(query)}/subscribe?args=` +
          encodeURIComponent(JSON.stringify(unref(args)))
      )
    ),
    args,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    DisplayInfoModel,
    onDisplay
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
    url += `?args=${encodeURIComponent(JSON.stringify(unref(args)))}`
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

export type GetLayoutResult = Zod.infer<typeof GetLayoutResultModel>
const GetLayoutResultModel = createResultType(LayoutModel, BaseFailModel)

export async function getLayout(address: Address): Promise<GetLayoutResult> {
  return await get(`/api/components/${address}/procedures/get-layout/call`, GetLayoutResultModel)
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
