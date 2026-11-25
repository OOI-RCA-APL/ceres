import type { Particle } from '@/api/particles'
import { formatNumber } from '@/utilities'

/** The value `particle` holds for `field`, or its whole data when no field is named. */
export function particleFieldValue(particle: Particle, field: string | null | undefined): unknown {
  return field == null || field === '' ? particle.data : particle.data[field]
}

/** `value` as a widget reads it out: numbers to at most `decimals` places, text as it is and
anything else as JSON. A field the record lacks reads "(No Value)". */
export function formatParticleValue(value: unknown, decimals: number): string {
  if (value === undefined) {
    return '(No Value)'
  }

  if (typeof value === 'number') {
    return formatNumber(value, decimals)
  }

  return typeof value === 'string' ? value : JSON.stringify(value)
}
