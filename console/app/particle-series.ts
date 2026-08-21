import { AddressSelector } from '@/api/address'
import { ChartWidgetParticleModel, ChartWidgetSeriesModel } from '@/workspace'
import type { ChartWidgetParticle, ChartWidgetSeries } from '@/workspace'

/** One field of one declared particle type, as the selector trees select them. */
export type ParticleFieldRef = {
  address: string
  type: string
  field: string
}

/** One declared particle type of one address, as the selector trees' type headers stand for. */
export type ParticleTypeRef = {
  address: string
  type: string
}

/** The key a selection tracks a field under, unique across the whole tree. */
export function fieldRefKey(ref: ParticleFieldRef): string {
  return `${ref.address}|${ref.type}|${ref.field}`
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

/** Turn `field` on or off for `address`'s `type`, merging into a single entry for that group and
removing it once its last field goes off.

The tree carries no connection of its own, so this reaches the group covering every connection
and never one of the narrowed copies beside it.
*/
export function toggleParticleField(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  field: string,
  value: boolean,
): ChartWidgetParticle[] {
  const current = seriesForGroup(particles, address, type)
  const hasField = current.some((series) => series.field === field)

  const series = value
    ? hasField
      ? current
      : [...current, ChartWidgetSeriesModel.parse({ field })]
    : current.filter((series) => series.field !== field)

  return withGroupSeries(particles, address, type, null, series)
}

/** Add one series entry for `address`'s `type`, merging into any existing entry for the group the
way a toggle does. */
export function addParticleSeries(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  series: ChartWidgetSeries,
): ChartWidgetParticle[] {
  return withGroupSeries(particles, address, type, null, [
    ...seriesForGroup(particles, address, type),
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

/** Narrow the group at `index` to `connection`, or to every connection when it is null. */
export function withGroupConnection(
  particles: ChartWidgetParticle[],
  index: number,
  connection: string | null,
): ChartWidgetParticle[] {
  return particles.map((particle, current) =>
    current === index ? { ...particle, connection } : particle,
  )
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
