import { defineStore } from 'pinia'
import { type MaybeRef, computed, unref } from 'vue'
import * as z from 'zod'

import { type Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient, useQuery } from '@/api/client'
import { MessageModel } from '@/api/messages'
import { AnyResultModel, ConnectivityModel } from '@/api/shared'

export type ProcedureType = z.infer<typeof ProcedureTypeModel>
export const ProcedureTypeModel = z.enum(['query', 'action'])

export type ProcedureArgsInfo = z.infer<typeof ProcedureArgumentsInfoModel>
export const ProcedureArgumentsInfoModel = z.object({
  json_schema: z.record(z.string(), z.any()),
  required: z.boolean(),
})

export type ProcedureDataOutputInfo = z.infer<typeof ProcedureValueOutputInfoModel>
export const ProcedureValueOutputInfoModel = z.object({
  type: z.literal('value'),
  json_schema: z.record(z.string(), z.any()),
})

export type ProcedureFileOutputInfo = z.infer<typeof ProcedureFileOutputInfoModel>
export const ProcedureFileOutputInfoModel = z.object({
  type: z.literal('file'),
  media: z.string().nullish(),
})

export type ProcedureStreamingOutputInfo = z.infer<typeof ProcedureStreamingOutputInfoModel>
export const ProcedureStreamingOutputInfoModel = z.object({
  type: z.literal('streaming'),
  media: z.string(),
})

export type ProcedureOutputInfo = z.infer<typeof ProcedureOutputInfoModel>
export const ProcedureOutputInfoModel = z.discriminatedUnion('type', [
  ProcedureValueOutputInfoModel,
  ProcedureStreamingOutputInfoModel,
  ProcedureFileOutputInfoModel,
])

export type ProcedurePermissions = z.infer<typeof ProcedurePermissionsModel>
export const ProcedurePermissionsModel = z.enum(['public', 'deny', 'view', 'operate', 'manage'])

const BaseProcedureInfoModel = z.object({
  name: z.string(),
  type: ProcedureTypeModel,
  live: z.boolean(),
  permissions: ProcedurePermissionsModel,
  arguments: ProcedureArgumentsInfoModel,
  output: ProcedureOutputInfoModel,
})

export type QueryInfo = z.infer<typeof QueryInfoModel>
export const QueryInfoModel = BaseProcedureInfoModel.extend({
  type: z.literal('query'),
})

export type ActionInfo = z.infer<typeof ActionInfoModel>
export const ActionInfoModel = BaseProcedureInfoModel.extend({
  type: z.literal('action'),
})

export type ProcedureInfo = z.infer<typeof ProcedureInfoModel>
export const ProcedureInfoModel = z.discriminatedUnion('type', [QueryInfoModel, ActionInfoModel])

export type ConnectionStateInfo = z.infer<typeof ConnectionStateInfoModel>
export const ConnectionStateInfoModel = z.object({
  name: z.string(),
  label: z.string().nullish(),
  description: z.string().nullish(),
  uri: z.string(),
  connectivity: ConnectivityModel,
})

export type JobInfo = z.infer<typeof JobInfoModel>
export const JobInfoModel = z.object({
  name: z.string(),
  action: z.string(),
  schedule: z.string(),
  next_run: z.string().nullable(),
})

export type ConnectionInfo = z.infer<typeof ConnectionInfoModel>
export const ConnectionInfoModel = z.object({
  name: z.string(),
  label: z.string().nullish(),
  description: z.string().nullish(),
  uri: z.string(),
})

export type ParticleFieldInfo = z.infer<typeof ParticleFieldInfoModel>
export const ParticleFieldInfoModel = z.object({
  name: z.string(),
  schema: z.record(z.string(), z.unknown()),
})

export type ParticleTypeInfo = z.infer<typeof ParticleTypeInfoModel>
export const ParticleTypeInfoModel = z.object({
  type: z.string(),
  description: z.string().nullish(),
  fields: z.array(ParticleFieldInfoModel),
  // The connections stamped on this type's stored records, empty when unattributed. A lower
  // bound that narrows pickers, never a set to filter queries on.
  connections: z.array(z.string()).default([]),
})

export type ComponentInfo = {
  name: string
  address: Address
  tags: string[]
  procedures: ProcedureInfo[]
  connections: ConnectionInfo[]
  components: ComponentInfo[]
  particles: ParticleTypeInfo[]
}

export const ComponentInfoModel: z.ZodType<ComponentInfo> = z.object({
  name: z.string(),
  address: AddressModel,
  tags: z.array(z.string()),
  procedures: z.array(ProcedureInfoModel),
  connections: z.array(ConnectionInfoModel),
  get components() {
    return z.array(ComponentInfoModel)
  },
  particles: z.array(ParticleTypeInfoModel),
}) as z.ZodType<ComponentInfo>

export const useComponents = defineStore('components', () => {
  const client = useClient()
  const auth = useAuth()

  async function getComponents(): Promise<ComponentInfo[]> {
    return await client.get('/api/components', { parse: z.array(ComponentInfoModel) })
  }

  /** Fetch a component's configuration. Rejects for callers with no access to the component. */
  async function getConfig(address: Address): Promise<Record<string, any> | null> {
    return await client.get(`/api/components/${address}/config`, {
      parse: z.record(z.string(), z.any()).nullable(),
    })
  }

  /** Fetch a component's scheduled jobs. Rejects for callers with no access to the component. */
  async function getJobs(address: Address): Promise<JobInfo[]> {
    return await client.get(`/api/components/${address}/jobs`, {
      parse: z.array(JobInfoModel),
    })
  }

  /** Fetch a component's connections with their live connectivity states. */
  async function getConnections(address: Address): Promise<ConnectionStateInfo[]> {
    return await client.get(`/api/components/${address}/connections`, {
      parse: z.array(ConnectionStateInfoModel),
    })
  }

  // The signal cancels the action as well as the request, since the engine ties the running
  // procedure to the request that asked for it and a client gone away cancels it.
  async function call(
    address: Address,
    procedure: string,
    args: MaybeRef<Record<string, any>> = {},
    options: { signal?: AbortSignal } = {},
  ) {
    return await client.post(`/api/components/${address}/procedures/${procedure}/call`, {
      data: unref(args),
      parse: AnyResultModel,
      init: { signal: options.signal },
    })
  }

  async function send(
    address: Address,
    connection: string,
    args: {
      data: string
    },
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

  // Plain functions over the reactive mapping. Callers in reactive contexts track the mapping
  // through the call itself.
  function get(address: Address | string) {
    return mapping[address.toString()] ?? null
  }

  function getDescendants(address: Address | string) {
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

  function getConnection(address: Address | string, name: string): ConnectionInfo | null {
    const component = get(address)
    return component?.connections.find((current) => current.name === name) ?? null
  }

  function getProcedure(address: Address, name: string): ProcedureInfo | null {
    const component = get(address)
    return component?.procedures.find((current) => current.name === name) ?? null
  }

  function getQuery(address: Address, name: string): QueryInfo | null {
    const procedure = getProcedure(address, name)
    if (procedure?.type !== 'query') {
      return null
    }

    return procedure
  }

  function getAction(address: Address, name: string): ActionInfo | null {
    const procedure = getProcedure(address, name)
    if (procedure?.type !== 'action') {
      return null
    }

    return procedure
  }

  return {
    ...query,
    topLevel: computed(() => topLevel),
    all: computed(() => Object.values(mapping)),
    get,
    getDescendants,
    getConnection,
    getProcedure,
    getQuery,
    getAction,
    getConfig,
    getJobs,
    getConnections,
    call,
    send,
  }
})
