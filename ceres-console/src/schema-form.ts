import { getter } from '@/getter'
import { usePersisted } from '@/persistence'
import { MaybePromise, MaybeRef, Plain } from '@/utilities'
import AJV, { SchemaObject as BaseSchemaObject } from 'ajv'
import { cloneDeep, isEqual } from 'lodash'
import { computed, reactive, ref, unref } from 'vue'

export type SchemaObject = BaseSchemaObject & {
  $ref?: string
  type?: string | string[]
  title?: string
  properties?: Record<string, Schema>
  prefixItems?: Schema[]
  items?: Schema | Schema[]
  additionalItems?: Schema
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  required?: string[]
  default?: Plain
}

export type Schema = boolean | SchemaObject
export type SchemaFormOptions = {
  initial?: Plain
  editing?: boolean
  schema: MaybeRef<Schema>
  persist?: MaybeRef<string | undefined>
  inline?: MaybeRef<boolean>
  onSubmit?: (value: any) => MaybePromise<SchemaFormState | void>
}

export type SchemaFormState = 'viewing' | 'editing' | 'submitting' | 'submitted'

export type SchemaForm = ReturnType<typeof createSchemaForm>

function get(object: Plain | undefined, path: SchemaPath): Plain | undefined {
  let current: any = object
  for (const index of path) {
    if (current == null) {
      return undefined
    }
    if (typeof current !== 'object') {
      return undefined
    }

    current = current[index]
  }

  return current
}

export function createSchemaForm({ ...options }: SchemaFormOptions) {
  const onSubmit = options.onSubmit
  const rootSchema = computed(() => unref(options.schema))
  const persist = computed(() => unref(options.persist))
  const inline = computed(() => unref(options.inline) ?? false)
  const state = ref<SchemaFormState>(
    options.editing == null || options.editing ? 'editing' : 'viewing'
  )
  const persisted = usePersisted({
    schema: ({ object, unknown }) =>
      object({
        value: unknown().default(() => getDefault(rootSchema.value)),
      }),
    methods: computed(() => (persist.value ? [{ type: 'local-storage', key: persist.value }] : [])),
  })

  if (options.hasOwnProperty('initial')) {
    persisted.value = cloneDeep(options.initial)
  }

  const ajv = computed(
    () =>
      new AJV({
        allErrors: true,
        validateFormats: false,
      })
  )

  const compilation = computed(() => {
    try {
      return {
        validator: ajv.value.compile(rootSchema.value),
        error: null,
      }
    } catch (error) {
      return {
        validator: null,
        error: error instanceof Error ? error : Error('unknown schema error'),
      }
    }
  })

  const schemaError = computed(() => compilation.value.error)
  const validator = computed(() => compilation.value.validator)
  const validationErrors = computed(() => {
    if (validator.value == null) {
      return []
    }

    validator.value(persisted.value)
    return validator.value.errors ?? []
  })

  function resolve(schema: Schema): Schema | undefined {
    if (typeof schema === 'boolean') {
      return schema
    }

    if (schema.$ref == null) {
      return schema
    }

    if (!schema.$ref.startsWith('#/')) {
      return undefined
    }

    const path = schema.$ref
      .split('/')
      .slice(1)
      .map((current) => {
        const number = Number(current)
        if (Number.isNaN(number)) {
          return current
        }

        return number
      })

    const target = get(rootSchema.value, path)
    if (target == null || typeof target !== 'object' || Array.isArray(target)) {
      return undefined
    }

    if (typeof schema !== 'object') {
      return undefined
    }

    const result: SchemaObject = {
      ...target,
      ...schema,
    }

    result.title = String(target.title ?? schema.title ?? String(path[path.length - 1] ?? ''))
    delete result['$ref']
    return result
  }

  function getDefault(pathOrSchema: SchemaPath | Schema = []): Plain | undefined {
    const schema: Schema | undefined = Array.isArray(pathOrSchema)
      ? getSchema(pathOrSchema)
      : resolve(pathOrSchema)
    if (schema == null) {
      return undefined
    }
    if (typeof schema === 'boolean') {
      return undefined
    }

    if (schema.default !== undefined) {
      return JSON.parse(JSON.stringify(schema.default))
    }

    const type = (Array.isArray(schema.type) ? schema[0] : schema.type) ?? undefined
    switch (type) {
      case 'null':
        return null
      case 'boolean':
      case 'integer':
      case 'number':
        let number = 0
        if (schema.minimum != null && number < schema.minimum) {
          number = schema.minimum
        } else if (schema.exclusiveMinimum && number <= schema.exclusiveMinimum) {
          number = Number(schema.exclusiveMinimum) + 1
        } else if (schema.maximum != null && number > schema.maximum) {
          number = schema.maximum
        } else if (schema.exclusiveMaximum && number >= schema.exclusiveMaximum) {
          number = Number(schema.exclusiveMaximum) - 1
        }

        if (schema.type === 'boolean') {
          return number !== 0
        }

        return number
      case 'string':
        return ''
      case 'array':
        return []
      case 'object':
        const object: Record<string, any> = {}
        for (const [property, subschema] of Object.entries(schema.properties ?? {})) {
          const isRequired = schema.required?.includes(property) ?? false
          if (isRequired) {
            object[property] = getDefault(subschema)
          } else {
            object[property] = undefined
          }
        }

        return object
    }

    return undefined
  }

  function getSchema(path: SchemaPath): Schema | undefined {
    let current: Schema | undefined = rootSchema.value

    for (const index of path) {
      if (current == null) {
        return undefined
      }

      current = resolve(current)
      if (current == null) {
        return undefined
      }

      if (typeof current === 'boolean') {
        return current
      }

      if (typeof index === 'string') {
        if (!isType(current, 'object')) {
          return undefined
        }
        if (typeof current.properties !== 'object') {
          return undefined
        }

        current = current.properties[index] ?? undefined
        continue
      }

      if (typeof index === 'number') {
        if (!isType(current, 'array')) {
          return undefined
        }

        const tupleSection =
          current.prefixItems ??
          (Array.isArray(current.items) ? current.items : undefined) ??
          undefined
        const arraySection =
          current.additionalItems ??
          (Array.isArray(current.items) ? undefined : current.items) ??
          undefined

        if (tupleSection == null && arraySection == null) {
          current = true
        } else if (Array.isArray(tupleSection) && index < tupleSection.length) {
          current = tupleSection[index]
        } else {
          current = arraySection
        }
        continue
      }
    }

    if (current == null) {
      return undefined
    }

    return resolve(current)
  }

  function getParentSchema(path: SchemaPath): SchemaObject | undefined {
    if (path.length === 0) {
      return undefined
    }

    return getSchema(path.slice(0, path.length - 1)) as SchemaObject | undefined
  }

  function getRequired(path: SchemaPath): boolean {
    const parent = getParentSchema(path)
    if (parent == null) {
      return true
    }

    if (typeof parent.required === 'boolean') {
      return parent.required
    }
    if (parent.required == null) {
      return false
    }

    const last = path[path.length - 1]
    return parent.required.includes(String(last))
  }

  function getLabel(path: SchemaPath): string | undefined {
    const schema = getSchema(path)
    if (schema == null) {
      return undefined
    }

    let label: string | number | undefined = undefined
    if (path.length > 0) {
      label = path[path.length - 1]
    } else if (typeof schema === 'object') {
      label = schema.title
    }

    if (label == null) {
      return undefined
    }
    if (typeof label === 'number') {
      return String(label + 1)
    }

    return String(label)
  }

  const isEmpty = computed(
    () => isEmptyObjectSchema(getSchema([])) && isEmptyObject(persisted.value)
  )
  const isDefault = computed(() => isEqual(persisted.value, getDefault()))

  const isValidSchema = computed(() => schemaError.value == null)
  const isValid = computed(() => isValidSchema.value && validationErrors.value.length === 0)
  const canSubmit = computed(() => isValid.value && state.value === 'editing')

  function reset() {
    assign(getDefault())
  }

  async function submit() {
    if (canSubmit.value && onSubmit) {
      state.value = 'submitting'
      try {
        state.value = (await onSubmit(persisted.value)) ?? 'editing'
      } catch {
        state.value = 'editing'
      }
    }
  }

  function edit() {
    if (state.value === 'editing') {
      return
    }

    state.value = 'editing'
    reset()
  }

  function discard() {
    state.value = 'viewing'
    reset()
  }

  function assign(value: unknown) {
    persisted.value = value
  }

  return reactive({
    value: computed(() => persisted.value),
    schema: rootSchema,
    state: computed(() => state.value),
    canSubmit,
    editable: computed(() => state.value === 'editing'),
    readonly: computed(() => state.value !== 'editing'),
    submitting: computed(() => state.value === 'submitting'),
    inline,
    reset,
    submit,
    edit,
    discard,
    assign,
    isEmpty,
    isDefault,
    isValid,
    isValidSchema,
    validator,
    schemaError,
    validationErrors,
    resolve: getter(() => rootSchema, resolve),
    getDefault: getter(() => rootSchema, getDefault),
    getSchema: getter(() => rootSchema, getSchema),
    getParentSchema: getter(() => rootSchema, getParentSchema),
    getRequired: getter(() => rootSchema, getRequired),
    getLabel: getter(() => rootSchema, getLabel),
  })
}

export type SchemaPath = ReadonlyArray<string | number>

export function isSchemaForm(value: unknown): value is SchemaForm {
  return value != null && typeof value === 'object' && 'schema' in value && 'validator' in value
}

export function isType(schema: Schema, type: string) {
  if (typeof schema === 'boolean' || schema === undefined) {
    return false
  }

  if (Array.isArray(schema.type)) {
    return schema.type.length === 1 && schema.type[0] === type
  }

  return schema.type === type
}

export function isEmptyObjectSchema(schema: Schema | null | undefined) {
  if (typeof schema === 'boolean' || schema?.properties == null) {
    return false
  }

  return Object.keys(schema.properties).length === 0
}

export function isEmptyObject(object: any) {
  return typeof object === 'object' && !Array.isArray(object) && Object.keys(object).length === 0
}
