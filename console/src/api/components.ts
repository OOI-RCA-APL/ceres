import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod, { ZodTypeAny } from 'zod'

import { Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ElementModel } from '@/api/elements'
import { AnyResultModel, ResultModel } from '@/api/shared'

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

const BaseProcedureInfoModel = Zod.object({
  name: Zod.string(),
  type: ProcedureTypeModel,
  live: Zod.boolean(),
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

export type ComponentRole = Zod.infer<typeof ComponentRoleModel>
export const ComponentRoleModel = Zod.enum(['connection', 'interface'])

export type ComponentInfo = {
  name: string
  address: Address
  roles: ComponentRole[]
  procedures: ProcedureInfo[]
  components: ComponentInfo[]
}

export const ComponentInfoModel: Zod.ZodType<ComponentInfo> = Zod.object({
  name: Zod.string(),
  address: AddressModel,
  roles: Zod.array(ComponentRoleModel),
  procedures: Zod.array(ProcedureInfoModel),
  components: Zod.lazy(() => Zod.array(ComponentInfoModel)),
}) as any

export type RenderResult = Zod.infer<typeof RenderResultModel>
const RenderResultModel = ResultModel(ElementModel)

export const useComponents = defineStore('components', () => {
  const client = useClient()
  const auth = useAuth()

  async function getComponent(address: Address) {
    try {
      return await client.get(`/api/components/${address}`, {
        parse: ComponentInfoModel,
      })
    } catch {
      return null
    }
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

  function useElementStream<TModel extends ZodTypeAny>(
    address: MaybeRef<Address>,
    query: MaybeRef<string>,
    args: MaybeRef<Record<string, unknown>>,
    onMessage: (message: Zod.infer<TModel>) => unknown
  ) {
    return client.useStream({
      stream: computed(() => ({
        path: `/api/components/${unref(address)}/procedures/${unref(query)}/subscribe`,
        query: { arguments: unref(args) },
      })) as any,
      parse: ElementModel,
      onReceive: onMessage,
    })
  }

  async function render(address: Address): Promise<RenderResult> {
    return await client.get(`/api/components/${address}/procedures/render/call`, {
      parse: RenderResultModel,
    })
  }

  const query = useQuery({
    queryKey: computed(() => ['root-component', auth.user?.id ?? null]),
    queryFn: async () => {
      if (auth.user == null) {
        return null
      }

      return await getComponent(new Address('@'))
    },
  })

  const root = $computed<ComponentInfo | null>(() => query.data.value ?? null)

  const mapping = $computed<Record<string, ComponentInfo>>(() => {
    if (root == null) {
      return {}
    }

    const mapping: Record<string, ComponentInfo> = {}

    function traverse(current: ComponentInfo) {
      mapping[current.address.toString()] = current
      for (const child of current.components) {
        traverse(child)
      }
    }

    traverse(root)
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
    root: computed(() => root),
    get: computed(() => get),
    getDescendants: computed(() => getDescendants),
    all: computed(() => all),
    getProcedure: computed(() => getProcedure),
    getQuery: computed(() => getQuery),
    getAction: computed(() => getAction),
    call,
    useElementStream,
    render,
  }
})
