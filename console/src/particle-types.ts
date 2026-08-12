import { useQueries, useQuery } from '@tanstack/vue-query'
import { computed, MaybeRefOrGetter, toValue } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { describeSchemaType, isType, Schema } from '@/schema-form'
import { ChartWidgetParticle } from '@/workspace'

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

/** The display label for a field, its type in the schema form's vocabulary with the unit in
parentheses when the field declares one. */
export function describeFieldType(schema: Schema): string {
  const type = describeSchemaType(schema)
  const unit = describeFieldUnit(schema)
  return unit == null ? type : `${type} (${unit})`
}

/** `schema`'s description, when it carries one. */
export function describeFieldDescription(schema: unknown): string | undefined {
  return typeof schema === 'object' && schema != null
    ? (schema as { description?: string }).description
    : undefined
}

/** The Y axis unit a chart derives when its setting is blank, the units its plotted fields
declare, joined when they differ. `resolveAddress` maps a particle entry's address selector
to the concrete address its types are keyed by. */
export function deriveChartUnit(
  particles: ChartWidgetParticle[],
  resolveAddress: (address: ChartWidgetParticle['address']) => string | null,
  typesByAddress: Map<string, ParticleTypeInfo[]>
): string {
  const units = new Set<string>()
  for (const particle of particles) {
    const address = resolveAddress(particle.address)
    const info =
      address == null
        ? undefined
        : typesByAddress.get(address)?.find((type) => type.type === particle.type)
    if (info == null) {
      continue
    }

    for (const series of particle.series) {
      const field = info.fields.find((field) => field.name === series.field)
      const fieldUnit = field == null ? undefined : describeFieldUnit(field.schema)
      if (fieldUnit != null) {
        units.add(fieldUnit)
      }
    }
  }

  return [...units].join(', ')
}

/** The measurement unit `schema` carries, published by the `Unit()` field marker.

An optional field holds the unit on its non-null `anyOf` member rather than at the top, so
union members are searched too.
*/
export function describeFieldUnit(schema: unknown): string | undefined {
  if (typeof schema !== 'object' || schema == null) {
    return undefined
  }

  const { unit, anyOf } = schema as { unit?: unknown; anyOf?: unknown[] }
  if (typeof unit === 'string') {
    return unit
  }

  for (const member of anyOf ?? []) {
    const found = describeFieldUnit(member)
    if (found != null) {
      return found
    }
  }

  return undefined
}
