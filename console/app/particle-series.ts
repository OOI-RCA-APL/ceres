import { AddressSelector } from '@/api/address'
import { ChartWidgetParticleModel, ChartWidgetSeriesModel } from '@/workspace'
import type { ChartWidgetParticle, ChartWidgetSeries } from '@/workspace'

/** One field of one declared particle type on one connection, as the picker selects them.
`connection` is null for a type no connection is known to produce. */
export type ParticleFieldRef = {
  address: string
  type: string
  connection: string | null
  field: string
}

/** One declared particle type of one address on one connection, as the picker's type headers
stand for. */
export type ParticleTypeRef = {
  address: string
  type: string
  connection: string | null
}

/** The key a selection tracks a type under, unique across the whole tree. A type with no
connection keeps the key it had before connections were told apart, which remembered tree
expansion is stored under. */
export function typeRefKey(ref: ParticleTypeRef): string {
  const base = `${ref.address}|${ref.type}`
  return ref.connection == null ? base : `${base}|${ref.connection}`
}

/** The key a selection tracks a field under, unique across the whole tree. */
export function fieldRefKey(ref: ParticleFieldRef): string {
  return `${typeRefKey(ref)}||${ref.field}`
}

/** The connection a group is narrowed to, `null` standing for every connection. */
export function groupConnection(particle: ChartWidgetParticle): string | null {
  return particle.connection ?? null
}

function isSameGroup(
  particle: ChartWidgetParticle,
  address: string,
  type: string,
  connection: string | null,
): boolean {
  return (
    (particle.address?.toString() ?? null) === address &&
    particle.type === type &&
    groupConnection(particle) === connection
  )
}

/** Every series `address`'s `type` carries on `connection`, merged across any duplicate entries a
stored widget carries for the same three. */
export function seriesForGroup(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  connection: string | null = null,
): ChartWidgetSeries[] {
  return particles
    .filter((particle) => isSameGroup(particle, address, type, connection))
    .flatMap((particle) => particle.series)
}

/** Replace every entry for the group with one carrying `series`, dropping it entirely once
`series` is empty. Entries this group does not touch keep their order. */
function withGroupSeries(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  connection: string | null,
  series: ChartWidgetSeries[],
): ChartWidgetParticle[] {
  const merged: ChartWidgetParticle[] = []
  let inserted = false

  function group() {
    return ChartWidgetParticleModel.parse({
      address: new AddressSelector(address),
      type,
      connection,
      series,
    })
  }

  for (const particle of particles) {
    if (!isSameGroup(particle, address, type, connection)) {
      merged.push(particle)
      continue
    }

    if (!inserted && series.length > 0) {
      merged.push(group())
      inserted = true
    }
  }

  if (!inserted && series.length > 0) {
    merged.push(group())
  }

  return merged
}

/** Turn `ref`'s field on or off, merging into a single entry for its address, type and connection
and removing that entry once its last field goes off. */
export function toggleParticleField(
  particles: ChartWidgetParticle[],
  ref: ParticleFieldRef,
  value: boolean,
): ChartWidgetParticle[] {
  const { address, type, connection, field } = ref
  const current = seriesForGroup(particles, address, type, connection)
  const hasField = current.some((series) => series.field === field)

  const series = value
    ? hasField
      ? current
      : [...current, ChartWidgetSeriesModel.parse({ field })]
    : current.filter((series) => series.field !== field)

  return withGroupSeries(particles, address, type, connection, series)
}

/** Add one series entry for `address`'s `type` on `connection`, merging into any existing entry
for the group the way a toggle does. */
export function addParticleSeries(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  series: ChartWidgetSeries,
  connection: string | null = null,
): ChartWidgetParticle[] {
  return withGroupSeries(particles, address, type, connection, [
    ...seriesForGroup(particles, address, type, connection),
    series,
  ])
}

/** Copy the group at `index`, giving every series of the copy an ID of its own so the chart
draws it as its own line. The copy sits directly after the original. */
export function duplicateParticleGroup(
  particles: ChartWidgetParticle[],
  index: number,
): ChartWidgetParticle[] {
  const original = particles[index]
  if (original == null) {
    return particles
  }

  const copy = ChartWidgetParticleModel.parse({
    address: original.address,
    type: original.type,
    connection: original.connection,
    // Parsed without an ID so the model mints a fresh one, and without a color so the copy
    // takes the next of the palette rather than the original's line.
    series: original.series.map((series) => ({ field: series.field, label: series.label })),
  })

  return [...particles.slice(0, index + 1), copy, ...particles.slice(index + 1)]
}

/** Remove one series entry by ID across every particle entry, dropping any entry left empty. */
export function removeParticleSeries(
  particles: ChartWidgetParticle[],
  seriesId: string,
): ChartWidgetParticle[] {
  return particles
    .map((particle) => ({
      ...particle,
      series: particle.series.filter((series) => series.id !== seriesId),
    }))
    .filter((particle) => particle.series.length > 0)
}
