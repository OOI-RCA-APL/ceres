import { MaybeRef } from '@vueuse/core'
import AJV, { SchemaObject as BaseSchemaObject } from 'ajv'
import { computed, inject, isRef, provide, reactive } from 'vue'
import { schemaFormInjectionKey } from './injection-keys'

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

function createSchemaForm(options: SchemaFormOptions) {
  const value = computed(() => (isRef(options.value) ? options.value.value : options.value))
  const schema = computed(() => (isRef(options.schema) ? options.schema.value : options.schema))

  const ajv = computed(
    () =>
      new AJV({
        allErrors: true,
      })
  )

  const compilation = computed(() => {
    try {
      return {
        validator: ajv.value.compile(schema.value),
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

    validator.value(value.value)
    return validator.value.errors
  })
  const validationErrorsText = computed(() =>
    ajv.value.errorsText(validationErrors.value, {
      separator: '\n',
      dataVar: `${getTitle([]) ?? 'Data'} `,
    })
  )

  function resolve(subschema: string | Schema): Schema | null {
    if (typeof subschema === 'boolean') {
      return subschema
    }

    let ref: string
    if (typeof subschema === 'object') {
      if (subschema.$ref == null) {
        return subschema
      }

      ref = subschema.$ref
    } else {
      ref = subschema
    }

    if (!ref.startsWith('#/')) {
      return null
    }

    const path = ref
      .split('/')
      .slice(1)
      .map((current) => {
        const number = Number(current)
        if (Number.isNaN(number)) {
          return current
        }

        return number
      })

    const target = get(path)
    if (target == null) {
      return null
    }

    if (typeof subschema !== 'object') {
      return target
    }

    const result = {
      ...target,
      ...subschema,
    }

    result.title = target.title ?? subschema.title ?? String(path[path.length - 1] ?? '')
    delete result['$ref']
    return result
  }

  function createDefault(
    schema: Schema
  ): null | boolean | number | string | unknown[] | Record<string, unknown> {
    if (typeof schema === 'boolean') {
      return false
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
      case undefined:
      case 'object':
        const object: Record<string, unknown> = {}
        for (const [property, subschema] of Object.entries(schema.properties ?? {})) {
          const required = schema.required?.includes(property) ?? false
          if (required) {
            object[property] = createDefault(subschema)
          } else {
            object[property] = undefined
          }
        }
        return object
    }

    return null
  }

  function get(path: SchemaPath): any | null {
    let current: any | null = schema.value
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

  function getSchema(path: SchemaPath): Schema | null {
    let current: Schema | null = schema.value

    for (const index of path) {
      if (current == null) {
        return null
      }

      current = resolve(current)
      if (current == null) {
        return null
      }

      if (typeof current === 'boolean') {
        return current
      }

      if (typeof index === 'string') {
        if (current.type !== 'object' && current.type != null) {
          return null
        }
        if (typeof current.properties !== 'object') {
          return null
        }

        current = current.properties[index] ?? null
        continue
      }

      if (typeof index === 'number') {
        if (current.type !== 'array') {
          return null
        }

        const tupleSection =
          current.prefixItems ?? (Array.isArray(current.items) ? current.items : null) ?? null
        const arraySection =
          current.additionalItems ?? (Array.isArray(current.items) ? null : current.items) ?? null

        if (Array.isArray(tupleSection) && index < tupleSection.length) {
          current = tupleSection[index]
        } else {
          current = arraySection
        }
        continue
      }
    }

    if (current == null) {
      return null
    }

    return resolve(current)
  }

  function getParentSchema(path: SchemaPath): SchemaObject | null {
    if (path.length === 0) {
      return null
    }

    return getSchema(path.slice(0, path.length - 1)) as SchemaObject | null
  }

  function isRequired(path: SchemaPath): boolean {
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
    value,
    schema,
    validator,
    schemaError,
    validationErrors,
    validationErrorsText,
    resolve,
    createDefault,
    getSchema,
    getParentSchema,
    isRequired,
    getTitle,
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

export type SchemaPath = (string | number)[]
