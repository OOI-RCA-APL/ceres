import { camelCase, debounce, difference, isEqual, kebabCase, pick } from 'lodash-es'
import {
  computed,
  getCurrentScope,
  isReactive,
  onScopeDispose,
  reactive,
  watch,
  type MaybeRefOrGetter,
  toValue,
} from 'vue'
import type { Router } from 'vue-router'
import * as z from 'zod'

import type { Address } from '@/api/address'

type Mapping = Record<string, any>
export type BaseSchema = z.ZodObject<any>
export type BaseData<TSchema extends BaseSchema> = z.infer<TSchema>

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
  LocalStoragePersistenceMethod<TData> | URLPersistenceMethod<TData>

export type UsePersistedOptions<TData extends BaseData<TSchema>, TSchema extends BaseSchema> = {
  data?: TData
  schema: TSchema | ((zod: typeof z) => TSchema)
  methods: MaybeRefOrGetter<PersistenceMethod<TData>[]>
}

export type KeyInput = (Address | string)[] | string | Address

function resolveKey(key: KeyInput): string {
  if (Array.isArray(key)) {
    return key.map((part) => part.toString()).join('/')
  }

  return key.toString()
}

function storageGet(key: string): unknown {
  const raw = localStorage.getItem(key)
  if (raw == null) {
    return null
  }

  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function storageSet(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function usePersisted<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  options: UsePersistedOptions<TData, TSchema>,
): TData {
  const schema = typeof options.schema == 'function' ? options.schema(z) : options.schema
  const methods = computed(() => toValue(options.methods))

  // The methods last actually read or written, held for the flush on dispose. The methods can
  // derive from the route, and by the time the scope is being torn down the route may already
  // belong to another page, so asking the computed again then can throw where these stay what
  // they were.
  let lastMethods: PersistenceMethod<TData>[] = []

  function currentMethods() {
    lastMethods = methods.value
    return lastMethods
  }

  let data = (options.data ?? schema.parse({})) as TData
  if (!isReactive(data)) {
    data = reactive(data) as TData
  }

  function read() {
    for (const method of currentMethods()) {
      const loaded =
        method.type === 'local-storage'
          ? readFromStorage<TData, TSchema>(resolveKey(method.key), schema)
          : readFromUrl<TData, TSchema>(schema)

      if (loaded != null) {
        load(data, loaded, method)
      }
    }
  }

  function write() {
    for (const method of currentMethods()) {
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
    }, 50),
  )

  // A consumer that confirms a choice and unmounts in the same breath would lose the debounced
  // write, since the timer outlives the watcher that would have run it. Storage is flushed on the
  // way out. The URL is not, because by then the location may already belong to another page.
  if (getCurrentScope() != null) {
    onScopeDispose(() => {
      for (const method of lastMethods) {
        if (method.type === 'local-storage') {
          writeToStorage(method, data)
        }
      }
    })
  }

  return data
}

function getFields<TData extends Mapping>(data: TData, method: BasePersistenceMethod<TData>) {
  return difference(method.include ?? Object.keys(data), method.exclude ?? [])
}

function load<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  data: TData,
  loaded: Partial<TData>,
  method: BasePersistenceMethod<TData>,
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
  schema: TSchema,
): Partial<TData> | null {
  try {
    return schema.partial().parse(storageGet(key)) as TData
  } catch {
    return null
  }
}

function writeToStorage<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  method: LocalStoragePersistenceMethod<TData>,
  data: TData,
) {
  storageSet(resolveKey(method.key), pick(data, getFields(data, method)))
}

function readFromUrl<TData extends BaseData<TSchema>, TSchema extends BaseSchema>(
  schema: TSchema,
): Partial<TData> | null {
  const data: Record<string, unknown> = {}
  const search = new URL(window.location.href).searchParams

  for (const key of new Set(search.keys())) {
    const field = camelCase(key)

    // An array field takes every appearance of its key, which is how a router writes a list and
    // how one reaches the page from a hand-written link.
    if (isFieldOfType(schema, field, 'array')) {
      const values = search.getAll(key)
      if (isArrayFieldOfType(schema, field, 'boolean')) {
        data[field] = values.map(Boolean)
      } else if (isArrayFieldOfType(schema, field, 'number')) {
        data[field] = values.map(Number)
      } else if (isArrayFieldOfType(schema, field, 'enum')) {
        data[field] = values.map((value) => value.toUpperCase().replace(/-/g, '_'))
      } else {
        data[field] = values
      }

      continue
    }

    const value = search.get(key) ?? ''
    if (value === 'null') {
      data[field] = null
    } else if (isFieldOfType(schema, field, 'boolean')) {
      data[field] = Boolean(value)
    } else if (isFieldOfType(schema, field, 'number')) {
      data[field] = Number(value)
    } else if (isFieldOfType(schema, field, 'enum')) {
      data[field] = value.toUpperCase().replace(/-/g, '_')
    } else {
      data[field] = value
    }
  }

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
  schema: TSchema,
) {
  const fields = new Set(getFields(data, method))
  const url = new URL(window.location.href)
  const search = url.searchParams

  const defaults = schema.parse({})
  for (const [field, value] of Object.entries(data)) {
    const key = kebabCase(field)

    if (fields.has(field)) {
      if (isEqual(value, defaults[field])) {
        search.delete(key)
        continue
      }
    } else if (!search.has(key)) {
      search.delete(key)
      continue
    }

    if (isFieldOfType(schema, field, 'enum')) {
      search.set(key, String(value).replace(/_/g, '-').toLowerCase())
      continue
    }

    // One appearance of the key per entry, so a list survives values carrying whatever
    // punctuation they like and reads the same as the one a router writes.
    if (isFieldOfType(schema, field, 'array')) {
      search.delete(key)
      if (Array.isArray(value)) {
        const spell = isArrayFieldOfType(schema, field, 'enum')
          ? (entry: unknown) => String(entry).replace(/_/g, '-').toLowerCase()
          : String

        for (const entry of value) {
          search.append(key, spell(entry))
        }
      }

      continue
    }

    search.set(key, String(value))
  }

  const params = url.searchParams.toString()

  void method.router.replace(`${url.pathname}${params ? '?' + params : ''}`)
}

// Walk through optional/nullable/default wrappers to the underlying schema, comparing against the
// def type discriminator ('boolean', 'number', 'enum', 'array').
function isFieldOfType(schema: BaseSchema, field: string, type: string): boolean {
  let current: any = schema.shape[field]
  while (current != null) {
    if (current.def?.type === type) {
      return true
    }

    current = current.def?.innerType ?? null
  }

  return false
}

function isArrayFieldOfType(schema: BaseSchema, field: string, type: string): boolean {
  let current: any = schema.shape[field]
  while (current != null) {
    if (current.def?.type === 'array' && current.def?.element?.def?.type === type) {
      return true
    }

    current = current.def?.innerType ?? null
  }

  return false
}
