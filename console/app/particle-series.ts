import { AddressSelector } from '@/api/address'
import { ChartWidgetParticleModel, ChartWidgetSeriesModel } from '@/workspace'
import type { ChartWidgetParticle, ChartWidgetSeries } from '@/workspace'

/** One field of one declared particle type, as the selector trees select them. */
export type ParticleFieldRef = {
  address: string
  type: string
  field: string
}

/** The key a selection tracks a field under, unique across the whole tree. */
export function fieldRefKey(ref: ParticleFieldRef): string {
  return `${ref.address}|${ref.type}|${ref.field}`
}

function isSameGroup(particle: ChartWidgetParticle, address: string, type: string): boolean {
  return (particle.address?.toString() ?? null) === address && particle.type === type
}

/** Every series `address`'s `type` carries, merged across any duplicate entries a stored widget
carries for the same pair. */
export function seriesForGroup(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
): ChartWidgetSeries[] {
  return particles
    .filter((particle) => isSameGroup(particle, address, type))
    .flatMap((particle) => particle.series)
}

/** Replace every entry for `address`'s `type` with one carrying `series`, dropping the pair
entirely once `series` is empty. Entries this pair does not touch keep their order. */
export function withGroupSeries(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  series: ChartWidgetSeries[],
): ChartWidgetParticle[] {
  const merged: ChartWidgetParticle[] = []
  let inserted = false

  for (const particle of particles) {
    if (!isSameGroup(particle, address, type)) {
      merged.push(particle)
      continue
    }

    if (!inserted && series.length > 0) {
      merged.push(
        ChartWidgetParticleModel.parse({ address: new AddressSelector(address), type, series }),
      )
      inserted = true
    }
  }

  if (!inserted && series.length > 0) {
    merged.push(
      ChartWidgetParticleModel.parse({ address: new AddressSelector(address), type, series }),
    )
  }

  return merged
}

/** Turn `field` on or off for `address`'s `type`, merging into a single entry for that pair and
removing it once its last field goes off. */
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

  return withGroupSeries(particles, address, type, series)
}

/** Add one series entry for `address`'s `type`, merging into any existing entry for the pair the
way a toggle does. */
export function addParticleSeries(
  particles: ChartWidgetParticle[],
  address: string,
  type: string,
  series: ChartWidgetSeries,
): ChartWidgetParticle[] {
  return withGroupSeries(particles, address, type, [
    ...seriesForGroup(particles, address, type),
    series,
  ])
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
