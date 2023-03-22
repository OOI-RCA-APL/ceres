import { getter } from '@/getter'
import { schemaFormInjectionKey } from '@/injection-keys'
import { MaybeRef } from '@vueuse/core'
import AJV, { SchemaObject as BaseSchemaObject } from 'ajv'
import { computed, inject, isRef, provide, reactive } from 'vue'

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
  default?: unknown
}

export type Schema = boolean | SchemaObject
export type SchemaFormOptions = {
  value: MaybeRef<unknown>
  schema: MaybeRef<Schema>
}

export type SchemaForm = ReturnType<typeof createSchemaForm>

function get(object: unknown, path: SchemaPath): any | null {
  let current: any | null = object
  for (const index of path) {
    if (current == null) {
      return null
    }
    if (typeof current !== 'object') {
      return null
    }

    current = current[index] ?? null
  }

  return current
}

export function createSchemaForm(options: SchemaFormOptions) {
  const rootValue = computed(() => (isRef(options.value) ? options.value.value : options.value))
  const rootSchema = computed(() => (isRef(options.schema) ? options.schema.value : options.schema))

  const ajv = computed(
    () =>
      new AJV({
        allErrors: true,
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
      return null
    }

    validator.value(rootValue.value)
    return validator.value.errors
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
    if (target == null) {
      return undefined
    }

    if (typeof schema !== 'object') {
      return target
    }

    const result: SchemaObject = {
      ...target,
      ...schema,
    }

    result.title = target.title ?? schema.title ?? String(path[path.length - 1] ?? '')
    delete result['$ref']
    return result
  }

  function getDefault(
    pathOrSchema: SchemaPath | Schema
  ): null | boolean | number | string | unknown[] | Record<string, unknown> | undefined {
    const schema: Schema | undefined = Array.isArray(pathOrSchema)
      ? getSchema(pathOrSchema)
      : pathOrSchema
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
        const object: Record<string, unknown> = {}
        for (const [property, subschema] of Object.entries(schema.properties ?? {})) {
          const required = schema.required?.includes(property) ?? false
          if (required) {
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

        current = current.properties[index] ?? null
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

  function getTitle(path: SchemaPath): string | undefined {
    const schema = getSchema(path)
    if (schema == null) {
      return undefined
    }

    let label: string | number | undefined
    if (typeof schema === 'boolean' || schema.title == null) {
      label = path[path.length - 1]
    } else {
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

  return reactive({
    value: rootValue,
    schema: rootSchema,
    validator,
    schemaError,
    validationErrors,
    resolve: getter(() => rootSchema, resolve),
    getDefault: getter(() => rootSchema, getDefault),
    getSchema: getter(() => rootSchema, getSchema),
    getParentSchema: getter(() => rootSchema, getParentSchema),
    getRequired: getter(() => rootSchema, getRequired),
    getTitle: getter(() => rootSchema, getTitle),
  })
}

export function provideSchemaForm(options: SchemaFormOptions) {
  const form = createSchemaForm(options)
  provide(schemaFormInjectionKey, form)
  return form
}

export function useSchemaForm() {
  const form = inject(schemaFormInjectionKey, null)
  if (form == null) {
    throw new Error(`missing inject for ${schemaFormInjectionKey}`)
  }

  return form
}

export type SchemaPath = ReadonlyArray<string | number>

export function isType(schema: Schema, type: string) {
  if (typeof schema === 'boolean' || schema === undefined) {
    return false
  }

  if (Array.isArray(schema.type)) {
    return schema.type.length === 1 && schema.type[0] === type
  }

  return schema.type === type
}
