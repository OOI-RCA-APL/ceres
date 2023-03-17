import { MaybeRef } from '@vueuse/core'
import { Schema, Validator } from 'jsonschema'
import { computed, inject, InjectionKey, provide, reactive } from 'vue'

type SchemaFormOptions = {
  value: MaybeRef<unknown>
  schema: MaybeRef<Schema>
}
type SchemaForm = ReturnType<typeof createSchemaForm>

const key: InjectionKey<SchemaForm> = Symbol('schema-form')

function createSchemaForm(options: SchemaFormOptions) {
  const reactiveOptions = reactive(options)
  const value = computed(() => reactiveOptions.value)
  const schema = computed(() => reactiveOptions.schema)

  const validator = computed(() => {
    const validator = new Validator()
    return validator
  })

  const validation = computed(() => validator.value.validate(value.value, schema.value))

  function resolve(definition: string | Schema): Schema | null {
    let ref: string
    if (typeof definition === 'object') {
      if (definition.$ref == null) {
        return definition
      }

      ref = definition.$ref
    } else {
      ref = definition
    }

    if (!ref.startsWith('#/definitions')) {
      return null
    }

    const tokens = ref.split('/')
    const definitionKey = tokens[tokens.length - 1]

    const target = (schema.value.definitions ?? {})[definitionKey] ?? null
    if (target == null) {
      return null
    }

    if (typeof definition !== 'object') {
      return target
    }

    const result = {
      ...target,
      ...definition,
    }

    result.title = target.title ?? definition.title ?? definitionKey
    delete result['$ref']
    return result
  }

  function createDefault(
    schema: Schema
  ): null | boolean | number | string | unknown[] | Record<string, unknown> {
    const type = (Array.isArray(schema) ? schema[0] : schema.type) ?? undefined
    switch (type) {
      case 'null':
        return null
      case 'boolean':
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
          let required: boolean
          if (schema.required == null) {
            required = false
          } else if (typeof schema.required === 'boolean') {
            required = schema.required
          } else {
            required = schema.required.includes(property)
          }

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

  function get(path: Path): Schema | null {
    let current: Schema | null = schema.value

    for (const token of path) {
      if (current == null) {
        return null
      }

      current = resolve(current)
      if (current == null) {
        return null
      }

      if (typeof token === 'string') {
        if (current.type !== 'object' && current.type != null) {
          return null
        }
        if (typeof current.properties !== 'object') {
          return null
        }

        current = current.properties[token] ?? null
        continue
      }

      if (typeof token === 'number') {
        if (current.type !== 'array') {
          return null
        }

        const prefixItems: unknown = (current as any).prefixItems
        if (Array.isArray(prefixItems)) {
          if (token < prefixItems.length) {
            current = prefixItems[token]
          } else if (current.items) {
            current = Array.isArray(current.items) ? current.items[0] : current.items
          } else {
            return null
          }
        }
        continue
      }

      return null
    }

    if (current == null) {
      return null
    }

    return resolve(current)
  }

  function getParent(path: Path): Schema | null {
    if (path.length === 0) {
      return null
    }

    return get(path.slice(0, path.length - 1))
  }

  function isRequired(path: Path): boolean {
    const parent = getParent(path)
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

  function getLabel(path: Path): string | undefined {
    const schema = get(path)
    if (schema == null) {
      return undefined
    }

    const label = schema.title ?? path[path.length - 1] ?? null
    if (label == null) {
      return undefined
    }

    return String(label)
  }

  return reactive({
    value,
    schema,
    validator,
    validation,
    resolve,
    createDefault,
    get,
    getParent,
    isRequired,
    getLabel,
  })
}

export function provideSchemaForm(options: SchemaFormOptions) {
  const form = createSchemaForm(options)
  provide(key, form)
  return form
}

export function useSchemaForm() {
  return (
    inject(key, null) ??
    provideSchemaForm({
      value: {},
      schema: {},
    })
  )
}

export type Path = (string | number)[]
