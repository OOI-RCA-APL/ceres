import _ from 'lodash'
import { debounce, LocalStorage } from 'quasar'
import { computed, isReactive, reactive, Ref, unref, watch } from 'vue'
import { Router } from 'vue-router'
import Zod, { ZodArray, ZodBoolean, ZodNativeEnum, ZodNumber, ZodObject } from 'zod'

import { Address } from '@/api/address'

type MaybeRef<T> = Ref<T> | T

type Mapping = Record<string, any>
export type BaseSchema = ZodObject<any>
export type BaseData<TSchema extends BaseSchema> = Zod.infer<TSchema>

type BasePersistenceMethod<TData extends Mapping> = {
  include?: (keyof TData)[]
  exclude?: (keyof TData)[]
}

export type LocalStoragePersistenceMethod<TData extends Mapping> = {
  type: 'local-storage'
  key: (Address | string)[] | Address | string
} & BasePersistenceMethod<TData>

export type URLPersistenceMethod<TData extends Mapping> = {
  type: 'url'
  router: Router
} & BasePersistenceMethod<TData>

export type PersistenceMethod<TData extends Mapping> =
  | LocalStoragePersistenceMethod<TData>
  | URLPersistenceMethod<TData>

export type UsePersistedOptions<TData extends BaseData<TSchema>, TSchema extends BaseSchema> = {
  data?: TData
  schema: TSchema | ((zod: typeof Zod) => TSchema)
  methods: MaybeRef<PersistenceMethod<TData>[]>
}

export type KeyInput = (Address | string)[] | string | Address

function resolveKey(key: KeyInput): string {
  if (Array.isArray(key)) {
    return key.map((part) => part.toString()).join('/')
  }

  return key.toString()
}

export function usePersisted<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  options: UsePersistedOptions<TData, TSchema>
): TData {
  const schema = typeof options.schema == 'function' ? options.schema(Zod) : options.schema
  const methods = computed(() => unref(options.methods))

  let data = (options.data ?? schema.parse({})) as TData
  if (!isReactive(data)) {
    data = reactive(data) as TData
  }

  function read() {
    for (const method of methods.value) {
      let loaded: Partial<TData> | null = null
      if (method.type === 'local-storage') {
        loaded = readFromStorage(resolveKey(method.key), schema)
      } else if (method.type === 'url') {
        loaded = readFromUrl(schema)
      } else {
        continue
      }

      if (loaded != null) {
        load(data, loaded, method)
      }
    }
  }

  function write() {
    for (const method of methods.value) {
      if (method.type === 'local-storage') {
        writeToStorage(method, data)
      } else if (method.type === 'url') {
        writeToUrl(method, data, schema)
      }
    }
  }

  read()
  write()

  watch(
    data,
    debounce(() => {
      write()
    }, 50)
  )

  return data
}

function getFields<TData extends Mapping>(data: TData, method: BasePersistenceMethod<TData>) {
  return _.difference(method.include ?? Object.keys(data), method.exclude ?? [])
}

function load<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  data: TData,
  loaded: Partial<TData>,
  method: BasePersistenceMethod<TData>
) {
  const fields = getFields(data, method)
  for (const field of fields) {
    if (field in loaded) {
      data[field] = loaded[field] as TData[keyof TData]
    }
  }
}

function readFromStorage<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  key: string,
  schema: TSchema
): Partial<TData> | null {
  try {
    return schema.partial().parse(LocalStorage.getItem<TData>(key)) as TData
  } catch {
    return null
  }
}

function writeToStorage<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  method: LocalStoragePersistenceMethod<TData>,
  data: TData
) {
  LocalStorage.set(resolveKey(method.key), _.pick(data, getFields(data, method)))
}

function readFromUrl<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  schema: TSchema
): Partial<TData> | null {
  const data: Record<string, unknown> = {}
  const search = new URL(window.location.href).searchParams

  search.forEach((value, key) => {
    const field = _.camelCase(key)
    if (field in data) {
      return
    }

    if (value === 'null') {
      data[field] = null
    } else if (isFieldOfType(schema, field, ZodBoolean)) {
      data[field] = Boolean(value)
    } else if (isFieldOfType(schema, field, ZodNumber)) {
      data[field] = Number(value)
    } else if (isFieldOfType(schema, field, ZodNativeEnum)) {
      data[field] = value.toUpperCase().replace(/-/g, '_')
    } else if (isArrayFieldOfType(schema, field, ZodBoolean)) {
      data[field] = value.split(',').map(Boolean)
    } else if (isArrayFieldOfType(schema, field, ZodNumber)) {
      data[field] = value.split(',').map(Number)
    } else if (isArrayFieldOfType(schema, field, ZodNativeEnum)) {
      data[field] = value.split(',').map((value) => value.toUpperCase().replace(/-/g, '_'))
    } else if (isFieldOfType(schema, field, ZodArray)) {
      data[field] = value.split(',')
    } else {
      data[field] = value
    }
  })

  try {
    return schema.partial().parse(data) as Partial<TData>
  } catch (error) {
    console.error(error)
    return null
  }
}

function writeToUrl<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  method: URLPersistenceMethod<TData>,
  data: TData,
  schema: TSchema
) {
  const fields = new Set(getFields(data, method))
  const url = new URL(window.location.href)
  const search = url.searchParams

  const defaults = schema.parse({})
  for (const [field, value] of Object.entries(data)) {
    const key = _.kebabCase(field)

    if (fields.has(field)) {
      if (_.isEqual(value, defaults[field])) {
        search.delete(key)
        continue
      }
    } else if (!search.has(key)) {
      search.delete(key)
      continue
    }

    if (isFieldOfType(schema, field, ZodNativeEnum)) {
      search.set(key, String(value).replace(/_/g, '-').toLowerCase())
      continue
    }

    if (isArrayFieldOfType(schema, field, ZodNativeEnum)) {
      if (_.isArrayLike(value) && value.length > 0) {
        search.set(key, value.map((value: any) => value.replace(/_/g, '-').toLowerCase()).join(','))
      }

      continue
    }

    if (isFieldOfType(schema, field, ZodArray)) {
      if (_.isArrayLike(value) && value.length > 0) {
        search.set(key, value.join(','))
      }

      continue
    }

    search.set(key, value)
  }

  const params = url.searchParams.toString()
  const serialized = `${url.pathname}${params ? '?' + params : ''}`.replace(/%2C/g, ',')

  void method.router.replace(serialized)
}

function isFieldOfType(schema: BaseSchema, field: string, type: any): boolean {
  let current = schema.shape[field]
  while (current != null) {
    if (current instanceof type) {
      return true
    }

    current = current._def?.innerType
  }

  return false
}

function isArrayFieldOfType(schema: BaseSchema, field: string, type: any): boolean {
  let current = schema.shape[field]
  while (current != null) {
    if (current instanceof ZodArray && current._def.type instanceof type) {
      return true
    }

    current = current._def?.innerType
  }

  return false
}
