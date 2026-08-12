import { useQueries, useQuery } from '@tanstack/vue-query'
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

/** Declared particle types for several component addresses at once, keyed by address.

Shares its cache entries with `useParticleTypes` through the same query keys. Unparseable
addresses are dropped the same way that one disables its query.
*/
export function useParticleTypesByAddress(addresses: MaybeRefOrGetter<string[]>) {
  const engine = useEngine()

  const parsed = computed<Address[]>(() =>
    [...new Set(toValue(addresses))].flatMap((value) => {
      try {
        return [Address.parse(value)]
      } catch {
        return []
      }
    })
  )

  const queries = useQueries({
    queries: computed(() =>
      parsed.value.map((address) => ({
        queryKey: ['particle-types', address.toString()],
        queryFn: () => engine.components.getParticleTypes(address),
        retry: false,
      }))
    ),
  })

  const types = computed<Map<string, ParticleTypeInfo[]>>(() => {
    const map = new Map<string, ParticleTypeInfo[]>()
    parsed.value.forEach((address, index) => {
      map.set(address.toString(), queries.value[index]?.data ?? [])
    })

    return map
  })

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

/** The measurement unit `schema` carries, published by the `Unit()` field marker. */
export function describeFieldUnit(schema: unknown): string | undefined {
  const unit =
    typeof schema === 'object' && schema != null ? (schema as { unit?: unknown }).unit : undefined
  return typeof unit === 'string' ? unit : undefined
}
