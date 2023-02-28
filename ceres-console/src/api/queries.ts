import {
  Alert,
  AlertModel,
  ComponentInfo,
  ComponentInfoModel,
  Config,
  ConfigModel,
  Message,
  MessageModel,
  Result,
  ResultModel,
  Statistics,
  StatisticsModel,
  UnitInfo,
  UnitInfoModel,
} from '@/api/models'
import { DisplayInfoModel } from '@/display'
import { useSettings } from '@/settings'
import { useIntervalFn } from '@vueuse/core'
import moment from 'moment'
import { defineStore } from 'pinia'
import { computed, isRef, ref, watch, watchEffect } from 'vue'
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

export async function getUnit(name: string): Promise<UnitInfo | null> {
  return await getOrNull(`/api/units/${name}`, UnitInfoModel)
}

export async function getComponent(unit: string, name: string): Promise<ComponentInfo | null> {
  return await getOrNull(`/api/units/${unit}/components/${name}`, ComponentInfoModel)
}

export async function getMessages(params: {
  source?: string
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
  source?: string
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<Alert[]> {
  return await get(`/api/alerts${createQueryParams(params)}`, Zod.array(AlertModel))
}

export async function getStatistics(params: {
  within?: number
  after?: string
  before?: string
}): Promise<Statistics> {
  return await get(`/api/statistics${createQueryParams(params)}`, StatisticsModel)
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

export function useMessageStream<TModel extends ZodTypeAny>(
  params: MaybeRef<{
    source?: string
    search?: string
  }>,
  onReceive: (message: Zod.infer<TModel>) => unknown
) {
  useStream(
    computed(() =>
      getWebSocketURI(
        `/api/message-stream${createQueryParams(isRef(params) ? params.value : params)}`
      )
    ),
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    MessageModel,
    onReceive
  )
}

export function useAlertStream<TModel extends ZodTypeAny>(
  params: MaybeRef<{
    source?: string
    search?: string
  }>,
  onReceive: (alert: Zod.infer<TModel>) => unknown
) {
  useStream(
    computed(() =>
      getWebSocketURI(
        `/api/alert-stream${createQueryParams(isRef(params) ? params.value : params)}`
      )
    ),
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    AlertModel,
    onReceive
  )
}

export const useConfig = defineStore('config', () => {
  const query = useQuery(['config'], getConfig, { retry: false })

  const data = $computed(() => query.data.value as Config)
  const error = $computed(() => query.error)

  async function load() {
    await query.suspense()
  }

  function getUnit(unitName: string) {
    return data.units.find((unit) => unit.name === unitName) ?? null
  }

  function getComponent(unitName: string, componentName: string) {
    return getUnit(unitName)?.components.find((component) => component.name === componentName)
  }

  return {
    data: $$(data),
    error: $$(error),
    load,
    getUnit,
    getComponent,
  }
})

export const useStatistics = defineStore('statistics', () => {
  const settings = useSettings()
  const query = useQuery(
    ['statistics'],
    async () =>
      await getStatistics({
        within: settings.statisticsDuration,
      })
  )

  const data = $computed(() => query.data.value as Statistics)
  const error = $computed(() => query.error)

  async function load() {
    await query.suspense()
  }

  useIntervalFn(async () => {
    await query.refetch.value()
  }, moment.duration(30, 's').asMilliseconds())

  watch(
    computed(() => settings.statisticsDuration),
    async () => {
      query.refetch.value()
    }
  )

  return {
    data: $$(data),
    error: $$(error),
    dataUpdatedAt: computed(() =>
      query.dataUpdatedAt.value ? moment(query.dataUpdatedAt.value) : null
    ),
    errorUpdatedAt: computed(() =>
      query.dataUpdatedAt.value ? moment(query.errorUpdatedAt.value) : null
    ),
    load,
  }
})

async function get<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url)
  const json = await response.json()
  return await model.parseAsync(json)
}

async function getOrNull<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel
): Promise<Zod.infer<TModel> | null> {
  const response = await fetch(url)
  if (response.status >= 400) {
    return null
  }

  const json = await response.json()
  return await model.parseAsync(json)
}

async function post<TModel extends ZodTypeAny>(
  url: string | URL,
  model: TModel,
  data?: unknown
): Promise<Zod.infer<TModel>> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: data != null ? JSON.stringify(data) : undefined,
  })

  const json = await response.json()
  return await model.parseAsync(json)
}

function createQueryParams(values: Record<string, string | number | null | undefined>): string {
  const result = new URLSearchParams()
  for (const key of Object.keys(values)) {
    const value = values[key]
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

function useStream<TModel extends ZodTypeAny>(
  url: MaybeRef<string | URL>,
  model: TModel,
  onMessage: (message: Zod.infer<TModel>) => unknown
) {
  const urlRef = isRef(url) ? url : ref(url)
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

      // console.log(`message on '${url}': '${JSON.stringify(event.data)}'`)

      const result = model.safeParse(data)
      if (result.success) {
        onMessage(result.data)
      } else {
        console.error(result.error)
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
      socket.close()
      setTimeout(() => {
        if (mounted) {
          socket = createSocket(urlRef.value, onDisconnect)
        }
      }, 250)
    }

    let socket = createSocket(urlRef.value, onDisconnect)

    function onUnload() {
      if (socket.readyState == WebSocket.OPEN) {
        socket.close()
      }
    }

    window.addEventListener('unload', onUnload)

    onCleanup(() => {
      mounted = false
      window.removeEventListener('unload', onUnload)
      socket.close()
    })
  })
}

export function useDisplayStream<TModel extends ZodTypeAny>(
  unitName: string,
  componentName: string,
  procedureName: string,
  onDisplay: (message: Zod.infer<TModel>) => unknown
) {
  return useStream(
    getWebSocketURI(
      `/api/units/${unitName}/components/${componentName}/procedures/${procedureName}/subscribe`
    ),
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    DisplayInfoModel,
    onDisplay
  )
}

const BaseOkModel = Zod.object({
  ok: Zod.literal(true),
})

const BaseFailModel = Zod.object({
  ok: Zod.literal(false),
  error: Zod.unknown(),
})

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

export async function sendMessage(
  unitName: string,
  componentName: string,
  data: string
): Promise<SendMessageResult> {
  return await post(
    `/api/units/${unitName}/components/${componentName}/procedures/send-message/call`,
    SendMessageResultModel,
    { data }
  )
}
