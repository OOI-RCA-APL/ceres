import { toValue } from 'vue'
import type { MaybeRefOrGetter } from 'vue'

import { Address } from '@/api/address'
import type { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { describeSchemaType, isType } from '@/schema-form'
import type { Schema } from '@/schema-form'
import type { ChartWidgetParticle } from '@/workspace'

/** Declared particle types for one component address, from the store behind `useEngine`.

The store is keyed by canonical addresses, so the lookup goes through `Address.parse`. A
wildcard or pipe selector, which fails that stricter parse, names no one component and
reads as no types.
*/
function declaredParticleTypes(
  engine: ReturnType<typeof useEngine>,
  value: string,
): ParticleTypeInfo[] {
  try {
    return engine.components.get(Address.parse(value).toString())?.particles ?? []
  } catch {
    return []
  }
}

/** Declared particle types for a component address, read from the components listing. */
export function useParticleTypes(address: MaybeRefOrGetter<string | null>) {
  const engine = useEngine()

  const types = $computed<ParticleTypeInfo[]>(() => {
    const value = toValue(address)
    return value == null ? [] : declaredParticleTypes(engine, value)
  })

  return { types: $$(types) }
}

/** Declared particle types for several component addresses at once, keyed by address as
given, canonical or not. */
export function useParticleTypesByAddress(addresses: MaybeRefOrGetter<string[]>) {
  const engine = useEngine()

  const types = $computed<Map<string, ParticleTypeInfo[]>>(() => {
    const map = new Map<string, ParticleTypeInfo[]>()
    for (const value of new Set(toValue(addresses))) {
      map.set(value, declaredParticleTypes(engine, value))
    }

    return map
  })

  return { types: $$(types) }
}

/** One entry of a component's data catalog: a declared particle type on one connection.

A type whose records carry several connections becomes one entry per connection, labeled by it,
so nothing built from an entry mixes two sources. A type one connection produces keeps the
look of a plain type but still names its connection, and one no connection is known to produce
reads from every connection, with `connection` null.
*/
export type ParticleTypeEntry = ParticleTypeInfo & {
  connection: string | null
  /** The connection's label, set only where the type has several connections to tell apart. */
  connectionLabel: string | null
}

/** The label `address`'s `connection` shows as, its own name when it declares none or the
component no longer lists it. */
export function connectionLabel(
  engine: ReturnType<typeof useEngine>,
  address: string,
  connection: string,
): string {
  return engine.components.getConnection(address, connection)?.label ?? connection
}

/** `types` as catalog entries, in declaration order and each type's connections in the order it
lists them, labeling a connection through `label`. */
export function particleTypeEntries(
  types: ParticleTypeInfo[],
  label: (connection: string) => string,
): ParticleTypeEntry[] {
  return types.flatMap((type): ParticleTypeEntry[] => {
    if (type.connections.length <= 1) {
      return [{ ...type, connection: type.connections[0] ?? null, connectionLabel: null }]
    }

    return type.connections.map((connection) => ({
      ...type,
      connection,
      connectionLabel: label(connection),
    }))
  })
}

/** The name an entry shows as, its connection's label leading where it has one. */
export function describeParticleTypeEntry(entry: ParticleTypeEntry): string {
  return entry.connectionLabel == null ? entry.type : `${entry.connectionLabel} › ${entry.type}`
}

/** Narrow `entries` of `address` to what a search string matches, case-insensitively.

Each word of the search must appear somewhere in the text a row composes of its address,
connection, type and field, so "pres 2" finds the "pressure" field of connection "Pressure 2". An
entry the search matches without its fields keeps every field, and one matched through its
fields keeps only those.
*/
export function filterParticleEntries(
  address: string,
  entries: ParticleTypeEntry[],
  search: string,
): ParticleTypeEntry[] {
  const words = search
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word !== '')
  if (words.length === 0) {
    return entries
  }

  const matches = (text: string) => words.every((word) => text.includes(word))

  return entries.flatMap((entry) => {
    const entryText = [
      address,
      entry.connectionLabel ?? '',
      entry.connection ?? '',
      entry.type,
      entry.description ?? '',
    ]
      .join(' ')
      .toLowerCase()
    if (matches(entryText)) {
      return [entry]
    }

    const fields = entry.fields.filter((field) =>
      matches(
        `${entryText} ${field.name} ${describeFieldDescription(field.schema) ?? ''}`.toLowerCase(),
      ),
    )

    return fields.length === 0 ? [] : [{ ...entry, fields }]
  })
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
function deriveChartUnit(
  particles: ChartWidgetParticle[],
  resolveAddress: (address: ChartWidgetParticle['address']) => string | null,
  typesByAddress: Map<string, ParticleTypeInfo[]>,
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

/** The derived Y axis unit for a chart widget, recomputed as its particles change.

Both the chart and its settings dialog show this, so the resolution lives here once.
`workspace` resolves each particle entry's address selector to the concrete component.
*/
export function useDerivedChartUnit(
  widget: MaybeRefOrGetter<{ particles?: ChartWidgetParticle[] }>,
  workspace: {
    resolveAddress: (
      value: ChartWidgetParticle['address'],
    ) => { toString(): string } | null | undefined
  },
) {
  const particles = $computed(() => toValue(widget).particles ?? [])

  const resolve = (value: ChartWidgetParticle['address']) =>
    workspace.resolveAddress(value)?.toString() ?? null

  const addresses = $computed(() =>
    particles.flatMap((particle) => {
      const resolved = resolve(particle.address)
      return resolved == null ? [] : [resolved]
    }),
  )

  const types = $(useParticleTypesByAddress(() => addresses).types)

  const unit = $computed(() => deriveChartUnit(particles, resolve, types))

  return { unit: $$(unit) }
}

/** The measurement unit `schema` carries, published by the `Unit()` field marker.

An optional field holds the unit on its non-null `anyOf` member rather than at the top, so
union members are searched too.
*/
function describeFieldUnit(schema: unknown): string | undefined {
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
