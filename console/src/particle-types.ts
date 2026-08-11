import { useQuery } from '@tanstack/vue-query'
import { computed, MaybeRefOrGetter, toValue } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { isType, Schema } from '@/schema-form'

/** Declared particle types for a component address.

The types endpoint takes a concrete address, so a wildcard or pipe selector, which fails
`Address`'s stricter parse, leaves the query disabled and `types` empty.
*/
export function useParticleTypes(address: MaybeRefOrGetter<string | null>) {
  const engine = useEngine()

  const componentAddress = computed<Address | null>(() => {
    const value = toValue(address)
    if (value == null) {
      return null
    }

    try {
      return Address.parse(value)
    } catch {
      return null
    }
  })

  const query = useQuery({
    queryKey: computed(() => ['particle-types', componentAddress.value?.toString() ?? null]),
    queryFn: () => engine.components.getParticleTypes(componentAddress.value as Address),
    enabled: computed(() => componentAddress.value != null),
    retry: false,
  })

  const types = computed<ParticleTypeInfo[]>(() => query.data.value ?? [])

  return { types }
}

/** Whether `schema` describes a field a chart can plot, a number or an integer. */
export function isPlottableField(schema: Schema): boolean {
  return isType(schema, 'number') || isType(schema, 'integer')
}

/** The JSON schema type `schema` names, in the console's own display vocabulary. */
export function describeFieldType(schema: Schema): string {
  for (const type of ['string', 'number', 'integer', 'boolean', 'array', 'object']) {
    if (isType(schema, type)) {
      return type
    }
  }

  return 'value'
}

/** `schema`'s description, when it carries one. */
export function describeFieldDescription(schema: unknown): string | undefined {
  return typeof schema === 'object' && schema != null
    ? (schema as { description?: string }).description
    : undefined
}
