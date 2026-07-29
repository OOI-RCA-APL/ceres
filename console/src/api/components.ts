import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

import { Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { MessageModel } from '@/api/messages'
import { AnyResultModel, ConnectivityModel } from '@/api/shared'

export type ProcedureType = Zod.infer<typeof ProcedureTypeModel>
export const ProcedureTypeModel = Zod.enum(['query', 'action'])

export type ProcedureArgsInfo = Zod.infer<typeof ProcedureArgumentsInfoModel>
export const ProcedureArgumentsInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
  required: Zod.boolean(),
})

export type ProcedureDataOutputInfo = Zod.infer<typeof ProcedureValueOutputInfoModel>
export const ProcedureValueOutputInfoModel = Zod.object({
  type: Zod.literal('value'),
  json_schema: Zod.record(Zod.string(), Zod.any()),
})

export type ProcedureFileOutputInfo = Zod.infer<typeof ProcedureFileOutputInfoModel>
export const ProcedureFileOutputInfoModel = Zod.object({
  type: Zod.literal('file'),
  media: Zod.string().nullish(),
})

export type ProcedureStreamingOutputInfo = Zod.infer<typeof ProcedureStreamingOutputInfoModel>
export const ProcedureStreamingOutputInfoModel = Zod.object({
  type: Zod.literal('streaming'),
  media: Zod.string(),
})

export type ProcedureOutputInfo = Zod.infer<typeof ProcedureOutputInfoModel>
export const ProcedureOutputInfoModel = Zod.discriminatedUnion('type', [
  ProcedureValueOutputInfoModel,
  ProcedureStreamingOutputInfoModel,
  ProcedureFileOutputInfoModel,
])

export type ProcedurePermissions = Zod.infer<typeof ProcedurePermissionsModel>
export const ProcedurePermissionsModel = Zod.enum(['public', 'deny', 'view', 'operate', 'manage'])

const BaseProcedureInfoModel = Zod.object({
  name: Zod.string(),
  type: ProcedureTypeModel,
  live: Zod.boolean(),
  permissions: ProcedurePermissionsModel,
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

export type ConnectionStateInfo = Zod.infer<typeof ConnectionStateInfoModel>
export const ConnectionStateInfoModel = Zod.object({
  name: Zod.string(),
  label: Zod.string(),
  connectivity: ConnectivityModel,
})

export type JobInfo = Zod.infer<typeof JobInfoModel>
export const JobInfoModel = Zod.object({
  name: Zod.string(),
  action: Zod.string(),
  schedule: Zod.string(),
  next_run: Zod.string().nullable(),
})

export type ConnectionInfo = Zod.infer<typeof ConnectionInfoModel>
export const ConnectionInfoModel = Zod.object({
  name: Zod.string(),
  label: Zod.string(),
})

export type ComponentInfo = {
  name: string
  address: Address
  tags: string[]
  procedures: ProcedureInfo[]
  connections: ConnectionInfo[]
  components: ComponentInfo[]
}

export const ComponentInfoModel: Zod.ZodType<ComponentInfo> = Zod.object({
  name: Zod.string(),
  address: AddressModel,
  tags: Zod.array(Zod.string()),
  procedures: Zod.array(ProcedureInfoModel),
  connections: Zod.array(ConnectionInfoModel),
  components: Zod.lazy(() => Zod.array(ComponentInfoModel)),
}) as any

export const useComponents = defineStore('components', () => {
  const client = useClient()
  const auth = useAuth()

  async function getComponents(): Promise<ComponentInfo[]> {
    return await client.get('/api/components', { parse: Zod.array(ComponentInfoModel) })
  }

  /** Fetch a component's configuration. Rejects for callers with no access to the component. */
  async function getConfig(address: Address): Promise<Record<string, any> | null> {
    return await client.get(`/api/components/${address}/config`, {
      parse: Zod.record(Zod.string(), Zod.any()).nullable(),
    })
  }

  /** Fetch a component's scheduled jobs. Rejects for callers with no access to the component. */
  async function getJobs(address: Address): Promise<JobInfo[]> {
    return await client.get(`/api/components/${address}/jobs`, {
      parse: Zod.array(JobInfoModel),
    })
  }

  /** Fetch a component's connections with their live connectivity states. */
  async function getConnections(address: Address): Promise<ConnectionStateInfo[]> {
    return await client.get(`/api/components/${address}/connections`, {
      parse: Zod.array(ConnectionStateInfoModel),
    })
  }

  async function call(
    address: Address,
    procedure: string,
    args: MaybeRef<Record<string, any>> = {}
  ) {
    return await client.post(`/api/components/${address}/procedures/${procedure}/call`, {
      data: unref(args),
      parse: AnyResultModel,
    })
  }

  async function send(
    address: Address,
    connection: string,
    args: {
      data: string
    }
  ) {
    return await client.post(`/api/components/${address}/connections/${connection}/send`, {
      data: args,
      parse: MessageModel,
    })
  }

  const query = useQuery({
    queryKey: computed(() => ['components', auth.user?.id ?? null]),
    queryFn: async () => {
      if (auth.user == null) {
        return null
      }

      return await getComponents()
    },
  })

  const topLevel = $computed<ComponentInfo[]>(() => query.data.value ?? [])

  const mapping = $computed<Record<string, ComponentInfo>>(() => {
    const mapping: Record<string, ComponentInfo> = {}

    function traverse(current: ComponentInfo) {
      mapping[current.address.toString()] = current
      for (const child of current.components) {
        traverse(child)
      }
    }

    for (const component of topLevel) {
      traverse(component)
    }

    return mapping
  })

  const get = $computed(
    () =>
      function get(address: Address | string) {
        return mapping[address.toString()] ?? null
      }
  )

  const getDescendants = $computed(
    () =>
      function (address: Address | string) {
        const component = get(address)
        if (component == null) {
          return []
        }

        const components: ComponentInfo[] = []
        function traverse(current: ComponentInfo) {
          components.push(current)
          for (const child of current.components) {
            traverse(child)
          }
        }

        for (const child of component.components) {
          traverse(child)
        }

        return components
      }
  )

  const all = $computed(() => Object.values(mapping))

  const getProcedure = $computed(
    () =>
      function getProcedure(address: Address, name: string): ProcedureInfo | null {
        const component = get(address)
        return component?.procedures.find((current) => current.name === name) ?? null
      }
  )

  const getQuery = $computed(
    () =>
      function getQuery(address: Address, name: string): QueryInfo | null {
        const procedure = getProcedure(address, name)
        if (procedure?.type !== 'query') {
          return null
        }

        return procedure
      }
  )

  const getAction = $computed(
    () =>
      function getAction(address: Address, name: string): ActionInfo | null {
        const procedure = getProcedure(address, name)
        if (procedure?.type !== 'action') {
          return null
        }

        return procedure
      }
  )

  return {
    ...query,
    topLevel: computed(() => topLevel),
    get: computed(() => get),
    getDescendants: computed(() => getDescendants),
    all: computed(() => all),
    getProcedure: computed(() => getProcedure),
    getQuery: computed(() => getQuery),
    getAction: computed(() => getAction),
    getConfig,
    getJobs,
    getConnections,
    call,
    send,
  }
})
