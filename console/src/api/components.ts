import { Address } from '@/address'
import { useAuth } from '@/api/auth'
import { ElementModel } from '@/api/elements'
import {
  BaseFailModel,
  BaseResultModel,
  createResultType,
  get,
  getOrNull,
  post,
} from '@/api/shared'
import { getter } from '@/getter'
import { useQuery } from '@tanstack/vue-query'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

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
  address: Zod.string().transform(Address.parse),
  roles: Zod.array(ComponentRoleModel),
  procedures: Zod.array(ProcedureInfoModel),
  components: Zod.lazy(() => Zod.array(ComponentInfoModel)),
}) as any

async function getComponent(address: Address): Promise<ComponentInfo | null> {
  return await getOrNull(`/api/components/${address}`, ComponentInfoModel)
}

async function getProcedure(address: Address, procedure: string): Promise<ProcedureInfo | null> {
  return await getOrNull(`/api/components/${address}/procedures/${procedure}`, ProcedureInfoModel)
}

async function call(address: Address, procedure: string, args: MaybeRef<Record<string, any>> = {}) {
  const url = `/api/components/${address}/procedures/${procedure}/call`
  return await post(url, BaseResultModel, unref(args))
}
export type RenderResult = Zod.infer<typeof RenderResultModel>
const RenderResultModel = createResultType(ElementModel, BaseFailModel)

async function render(address: Address): Promise<RenderResult> {
  return await get(`/api/components/${address}/procedures/render/call`, RenderResultModel)
}

export const useComponents = defineStore('components', () => {
  const auth = useAuth()
  const query = useQuery({
    queryKey: computed(() => ['root-component', auth.user?.id ?? null]),
    queryFn: async () => {
      if (auth.user == null) {
        return null
      }

      return await getComponent(new Address('@'))
    },
  })

  const root = computed<ComponentInfo | null>(() => query.data.value ?? null)

  const mapping = computed<Record<string, ComponentInfo>>(() => {
    if (root.value == null) {
      return {}
    }

    const mapping: Record<string, ComponentInfo> = {}

    function traverse(current: ComponentInfo) {
      mapping[current.address.toString()] = current
      for (const child of current.components) {
        traverse(child)
      }
    }

    traverse(root.value)
    return mapping
  })

  const get = getter(
    mapping,
    function getComponent(address: Address | string): ComponentInfo | null {
      return mapping.value[address.toString()] ?? null
    }
  )

  const all = computed(() => Object.values(mapping.value))

  return {
    ...query,
    root,
    get,
    all,
    getProcedure,
    call,
    render,
  }
})
