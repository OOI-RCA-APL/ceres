import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod, { ZodTypeAny } from 'zod'

import { Address, AddressModel } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useClient } from '@/api/client'
import { ElementModel } from '@/api/elements'
import { BaseFailModel, BaseResultModel, createResultType } from '@/api/shared'
import { getter } from '@/getter'

export type ProcedureType = Zod.infer<typeof ProcedureTypeModel>
export const ProcedureTypeModel = Zod.enum(['query', 'action'])

export type ProcedureArgsInfo = Zod.infer<typeof ProcedureArgumentsInfoModel>
export const ProcedureArgumentsInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
  required: Zod.boolean(),
})

export type ProcedureOutputInfo = Zod.infer<typeof ProcedureOutputInfoModel>
export const ProcedureOutputInfoModel = Zod.object({
  json_schema: Zod.record(Zod.string(), Zod.any()),
})

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
const RenderResultModel = createResultType(ElementModel, BaseFailModel)

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

  async function getProcedure(address: Address, procedure: string): Promise<ProcedureInfo | null> {
    try {
      return await client.get(`/api/components/${address}/procedures/${procedure}`, {
        parse: ProcedureInfoModel,
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
      parse: BaseResultModel,
    })
  }

  function useElementStream<TModel extends ZodTypeAny>(
    address: MaybeRef<Address>,
    query: MaybeRef<string>,
    args: MaybeRef<Record<string, unknown>>,
    onMessage: (message: Zod.infer<TModel>) => unknown
  ) {
    return client.useStream(
      computed(() => `/api/components/${unref(address)}/procedures/${unref(query)}/subscribe`),
      // @ts-ignore
      ElementModel,
      onMessage,
      computed(() => ({ query: { arguments: unref(args) } }))
    )
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

  const get = getter($$(mapping), (address: Address | string) => {
    return mapping[address.toString()] ?? null
  })

  const all = $computed(() => Object.values(mapping))

  return {
    ...query,
    root: computed(() => root),
    get,
    all: computed(() => all),
    getProcedure,
    call,
    useElementStream,
    render,
  }
})
