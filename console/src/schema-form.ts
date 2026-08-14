import AJV, { SchemaObject as BaseSchemaObject, ValidateFunction } from 'ajv'
import { cloneDeep, isEqual, upperFirst } from 'lodash-es'
import { computed, MaybeRefOrGetter, reactive, toValue } from 'vue'

import { KeyInput, usePersisted } from './persistence'

import { FormState } from '@/form'
import { getter } from '@/getter'
import { useTime } from '@/time'
import { MaybePromise, Plain } from '@/utilities'

export type SchemaObject = BaseSchemaObject & {
  $ref?: string
  type?: string | string[]
  anyOf?: Schema[]
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
  optional?: boolean
  default?: Plain
  enum?: Plain[]
}

export type Schema = boolean | SchemaObject
export type SchemaFormOptions = {
  value?: MaybeRefOrGetter<Plain>
  initial?: Plain
  readonly?: MaybeRefOrGetter<boolean>
  schema?: MaybeRefOrGetter<Schema>
  persist?: MaybeRefOrGetter<KeyInput>

  /** A heading drawn inside the form, under the root description and over the fields, so what the
  fields are for is said by the form itself rather than floated above it. */
  title?: MaybeRefOrGetter<string | undefined>
  onSubmit?: (value: any) => MaybePromise<SchemaFormState | void>
  onUpdate?: (value: any) => MaybePromise<void>
}

export type SchemaFormState = 'viewing' | 'editing' | 'submitting' | 'submitted'

export type SchemaForm = ReturnType<typeof useSchemaForm>

function get(object: unknown, path: SchemaPath): unknown | undefined {
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

export function useSchemaForm(options: SchemaFormOptions) {
  const hasModelValue = $computed(() => options.hasOwnProperty('value'))
  const modelValue = $computed(() => toValue(options.value))
  const rootSchema = $computed(() => toValue(options.schema))
  const readonly = $computed(() => toValue(options.readonly) ?? false)
  const onUpdate = $computed(() => options.onUpdate ?? (() => {}))
  const onSubmit = $computed(() => options.onSubmit ?? (() => {}))
  const persist = $computed(() => toValue(options.persist))
  const title = $computed(() => toValue(options.title))

  let state = $ref<SchemaFormState>(readonly ?? false ? 'viewing' : 'editing')

  const time = useTime()
  const persisted = usePersisted({
    schema: ({ object, unknown }) =>
      object({
        value: unknown().default(() => getInitialValue(rootSchema)),
      }),
    methods: computed(() => (persist ? [{ type: 'local-storage', key: persist }] : [])),
  })

  let value: unknown = $computed({
    get: () => (hasModelValue ? modelValue : persisted.value),
    set: (updated: unknown) => {
      if (hasModelValue) {
        onUpdate(updated)
      }

      persisted.value = updated
    },
  })

  if (options.hasOwnProperty('initial')) {
    value = cloneDeep(options.initial)
  }

  const ajv = $computed(
    () =>
      new AJV({
        allErrors: true,
        validateFormats: false,
      })
  )

  const compilation = $computed<{ validator: ValidateFunction<unknown>; error: Error }>(() => {
    try {
      return {
        validator: ajv.compile(rootSchema),
        error: null,
      }
    } catch (error) {
      return {
        validator: null,
        error: error instanceof Error ? error : Error('unknown schema error'),
      }
    }
  })

  const schemaError = $computed(() => compilation.error)
  const schemaErrorMessage = $computed(() => {
    if (schemaError == null) {
      return null
    }

    humanizeErrorMessage(schemaError.message)
  })

  const validator = $computed(() => compilation.validator)
  const validationErrors = $computed(() => {
    if (validator == null) {
      return []
    }

    validator(value)
    return validator.errors ?? []
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

    const target = get(rootSchema, path)
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

    result.title = String(
      (target as any).title ?? schema.title ?? String(path[path.length - 1] ?? '')
    )
    delete result['$ref']
    return result
  }

  function getDefault(pathOrSchema: SchemaPath | Schema = []): unknown | undefined {
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

    return undefined
  }

  function getInitialValue(pathOrSchema: SchemaPath | Schema = []): unknown | undefined {
    const schema: Schema | undefined = Array.isArray(pathOrSchema)
      ? getSchema(pathOrSchema)
      : resolve(pathOrSchema)
    if (schema == null) {
      return undefined
    }
    if (typeof schema === 'boolean') {
      return null // JSON (Any)
    }

    if (schema.default !== undefined) {
      return JSON.parse(JSON.stringify(schema.default))
    }

    if (schema.enum != null) {
      return schema.enum[0]
    }

    const type = (Array.isArray(schema.type) ? schema[0] : schema.type) ?? undefined
    if (type == null) {
      return null // JSON (Any)
    }

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
        if (schema.format === 'date-time') {
          return time.now.format('YYYY-MM-DD HH:mm:00.000')
        }
        if (schema.format === 'date') {
          return time.now.format('YYYY-MM-DD')
        }
        if (schema.format == null) {
          return ''
        }

        return undefined
      case 'array':
        return []
      case 'object':
        const object: Record<string, any> = {}
        for (const [property, subschema] of Object.entries(schema.properties ?? {})) {
          const isRequired = schema.required?.includes(property) ?? false
          if (isRequired) {
            object[property] = getInitialValue(subschema)
          }
        }

        return object
    }

    return undefined
  }

  function getSchema(path: SchemaPath): Schema | undefined {
    let current: Schema | undefined = rootSchema

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

  function getSchemaObject(path: SchemaPath): SchemaObject | undefined {
    const schema = getSchema(path)
    if (typeof schema === 'boolean') {
      return {}
    }

    return schema
  }

  function getParentSchema(path: SchemaPath): SchemaObject | undefined {
    if (path.length === 0) {
      return undefined
    }

    return getSchema(path.slice(0, path.length - 1)) as SchemaObject | undefined
  }

  function getRequired(path: SchemaPath): boolean {
    const schema = getSchema(path)
    if (schema != null && typeof schema === 'object' && schema.optional) {
      return false
    }

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
    if (typeof schema === 'object') {
      label = schema.title
    }
    if (label == null && path.length > 0) {
      label = path[path.length - 1]
    }

    if (label == null) {
      return undefined
    }
    if (typeof label === 'number') {
      return String(label + 1)
    }

    return String(label)
  }

  function getDescription(path: SchemaPath): string | undefined {
    const schema = getSchema(path)
    if (schema == null) {
      return undefined
    }

    if (typeof schema === 'object') {
      return schema.description
    }

    return undefined
  }

  const isEmpty = $computed(() => isEmptyObjectSchema(getSchema([])) && isEmptyObject(value))
  const isDefault = $computed(() => isEqual(value, getDefault()))
  const isInitialValue = $computed(() => isEqual(value, getInitialValue()))

  const isValidSchema = $computed(() => schemaError == null)
  const isValid = $computed(() => isValidSchema && validationErrors.length === 0)
  const canSubmit = $computed(() => isValid && state === 'editing')

  function reset() {
    value = getInitialValue()
  }

  async function submit() {
    if (canSubmit && onSubmit) {
      state = 'submitting'
      try {
        state = ((await onSubmit(value)) as FormState | undefined) ?? 'editing'
      } catch {
        state = 'editing'
      }
    }
  }

  function edit() {
    if (state === 'editing') {
      return
    }

    state = 'editing'
    reset()
  }

  function discard() {
    state = 'viewing'
    reset()
  }

  function getPathString(path: string | SchemaPath): string {
    if (typeof path !== 'string') {
      path = path.join('/')
    }

    if (path.length === 0) {
      path = '/'
    } else {
      if (!path.startsWith('/')) {
        path = '/' + path
      }
    }

    return path
  }

  function humanizeErrorMessage(message: string) {
    message = message.trim()
    if (message === '') {
      return 'Invalid value.'
    }

    message = upperFirst(message)
    if (!message.endsWith('.')) {
      message += '.'
    }

    return message
  }

  function getExactValidationErrorMessage(path: SchemaPath) {
    const pathString = getPathString(path)
    const message =
      validationErrors.find((error) => getPathString(error.instancePath) === pathString)?.message ??
      null

    if (message == null) {
      return null
    }

    return humanizeErrorMessage(message)
  }

  function getValidationErrorMessage(path: SchemaPath) {
    let message = getExactValidationErrorMessage(path)
    if (message?.includes('required property')) {
      return null
    }

    if (message == null) {
      const parent = path.length > 0 ? path.slice(0, path.length - 1) : null
      const parentSchema = parent != null ? getParentSchema(path) : null
      if (parent != null && (parentSchema == null || parentSchema.type === 'object')) {
        const parentError = getExactValidationErrorMessage(parent)
        const name = path[path.length - 1]
        if (parentError?.includes(`required property '${name}'`)) {
          message = `This value is required, but currently undefined.`
        }
      }
    }

    return message
  }

  return reactive({
    value: $$(value),
    schema: computed(() => rootSchema),
    title: computed(() => title),
    state: computed(() => state),
    canSubmit: computed(() => canSubmit),
    editable: computed(() => state === 'editing'),
    readonly: computed(() => state !== 'editing'),
    submitting: computed(() => state === 'submitting'),
    reset,
    submit,
    edit,
    discard,
    isEmpty: computed(() => isEmpty),
    isDefault: computed(() => isDefault),
    isInitialValue: computed(() => isInitialValue),
    isValid: computed(() => isValid),
    isValidSchema: computed(() => isValidSchema),
    validator: computed(() => validator),
    schemaError: computed(() => schemaError),
    schemaErrorMessage: computed(() => schemaErrorMessage),
    validationErrors: computed(() => validationErrors),
    resolve: getter($$(rootSchema), resolve),
    getDefault: getter($$(rootSchema), getDefault),
    getInitialValue: getter($$(rootSchema), getInitialValue),
    getSchema: getter($$(rootSchema), getSchema),
    getSchemaObject: getter($$(rootSchema), getSchemaObject),
    getParentSchema: getter($$(rootSchema), getParentSchema),
    getRequired: getter($$(rootSchema), getRequired),
    getLabel: getter($$(rootSchema), getLabel),
    getDescription: getter($$(rootSchema), getDescription),
    humanizeErrorMessage: getter(
      computed(() => null),
      humanizeErrorMessage
    ),
    getPathString: getter(
      computed(() => null),
      getPathString
    ),
    getValidationErrorMessage: getter($$(validationErrors), getValidationErrorMessage),
  })
}

export type SchemaPath = ReadonlyArray<string | number>

export function isSchemaForm(value: unknown): value is SchemaForm {
  return value != null && typeof value === 'object' && 'schema' in value && 'validator' in value
}

export function isType(schema: Schema, type: string): boolean {
  if (typeof schema === 'boolean' || schema === undefined) {
    return false
  }

  if (Array.isArray(schema.type)) {
    return schema.type.length === 1 && schema.type[0] === type
  }

  if (schema.anyOf) {
    return schema.anyOf.some((schema) => isType(schema, type))
  }

  return schema.type === type
}

/** Whether `schema` or one of its `anyOf` members carries `format`, the way an optional field
wraps its real schema in a union with null. */
export function hasFormat(schema: Schema, format: string): boolean {
  if (typeof schema === 'boolean' || schema == null) {
    return false
  }

  if (schema.format === format) {
    return true
  }

  return (schema.anyOf ?? []).some((member) => hasFormat(member, format))
}

/** The display name for the value `schema` describes, in the same vocabulary the form's own
controls hint with, such as `str`, `date-time`, and `duration`. */
export function describeSchemaType(schema: Schema): string {
  if (typeof schema === 'object' && schema != null && schema.enum != null) {
    return 'enum'
  }

  if (isType(schema, 'boolean')) {
    return 'boolean'
  }

  // Number-like unions read as plain numbers, so this check comes before the integer one.
  if (isType(schema, 'number')) {
    return 'number'
  }

  if (isType(schema, 'integer')) {
    return 'integer'
  }

  if (isType(schema, 'string')) {
    for (const format of ['date-time', 'date', 'duration', 'address-selector']) {
      if (hasFormat(schema, format)) {
        return format
      }
    }

    return 'str'
  }

  if (isType(schema, 'array')) {
    return 'array'
  }

  if (isType(schema, 'object')) {
    return 'object'
  }

  return 'value'
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
