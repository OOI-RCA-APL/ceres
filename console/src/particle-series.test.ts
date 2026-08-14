import { describe, expect, it } from 'vitest'

import { AddressSelector } from '@/api/address'
import {
  addParticleSeries,
  removeParticleSeries,
  seriesForGroup,
  toggleParticleField,
} from '@/particle-series'
import { ChartWidgetParticle, ChartWidgetParticleModel, ChartWidgetSeriesModel } from '@/workspace'

const address = '@sensor'

/** A particle entry for `address` and `type`, one series per field name given. */
function particle(type: string, ...fields: string[]): ChartWidgetParticle {
  return ChartWidgetParticleModel.parse({
    address: new AddressSelector(address),
    type,
    series: fields.map((field) => ({ field })),
  })
}

describe('toggleParticleField', () => {
  it('creates an entry for a field toggled on with no existing entry', () => {
    const result = toggleParticleField([], address, 'temperature', 'celsius', true)

    expect(result).toHaveLength(1)
    expect(result[0].address?.toString()).toBe(address)
    expect(result[0].type).toBe('temperature')
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius'])
  })

  it('adds a field to an existing entry rather than creating a second one', () => {
    const particles = [particle('temperature', 'celsius')]
    const result = toggleParticleField(particles, address, 'temperature', 'humidity', true)

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field).sort()).toEqual(['celsius', 'humidity'])
  })

  it('does not duplicate a field already toggled on', () => {
    const particles = [particle('temperature', 'celsius')]
    const result = toggleParticleField(particles, address, 'temperature', 'celsius', true)

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius'])
  })

  it('turns a field off, keeping the entry while another field remains', () => {
    const particles = [particle('temperature', 'celsius', 'humidity')]
    const result = toggleParticleField(particles, address, 'temperature', 'humidity', false)

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius'])
  })

  it('removes the entry once its last field turns off', () => {
    const particles = [particle('temperature', 'celsius')]
    const result = toggleParticleField(particles, address, 'temperature', 'celsius', false)

    expect(result).toHaveLength(0)
  })

  it('leaves entries for other addresses and types untouched', () => {
    const other = particle('humidity', 'percent')
    const particles = [other, particle('temperature', 'celsius')]
    const result = toggleParticleField(particles, address, 'temperature', 'celsius', false)

    expect(result).toEqual([other])
  })

  it('merges duplicate entries for the same address and type on write', () => {
    // A stored widget from the old free-form UI, which enforced no uniqueness on address and
    // type, can carry more than one entry for the same pair.
    const particles = [particle('temperature', 'celsius'), particle('temperature', 'humidity')]
    const result = toggleParticleField(particles, address, 'temperature', 'humidity', false)

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius'])
  })

  it('removes duplicate entries entirely once every field across them turns off', () => {
    const particles = [particle('temperature', 'celsius'), particle('temperature', 'humidity')]
    const withoutCelsius = toggleParticleField(particles, address, 'temperature', 'celsius', false)
    const result = toggleParticleField(withoutCelsius, address, 'temperature', 'humidity', false)

    expect(result).toHaveLength(0)
  })
})

describe('seriesForGroup', () => {
  it('aggregates series across duplicate entries for the same address and type', () => {
    const particles = [particle('temperature', 'celsius'), particle('temperature', 'humidity')]

    expect(seriesForGroup(particles, address, 'temperature').map((series) => series.field)).toEqual(
      ['celsius', 'humidity']
    )
  })

  it('returns nothing for a pair with no entries', () => {
    expect(seriesForGroup([particle('temperature', 'celsius')], address, 'humidity')).toEqual([])
  })
})

describe('addParticleSeries', () => {
  it('merges a manual entry into an existing entry for the same pair', () => {
    const particles = [particle('temperature', 'celsius')]
    const result = addParticleSeries(
      particles,
      address,
      'temperature',
      ChartWidgetSeriesModel.parse({ field: 'humidity' })
    )

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius', 'humidity'])
  })
})

describe('removeParticleSeries', () => {
  it('removes one series by ID, dropping the entry once it is left empty', () => {
    const particles = [particle('temperature', 'celsius')]
    const seriesId = particles[0].series[0].id

    expect(removeParticleSeries(particles, seriesId)).toEqual([])
  })

  it('finds a matching series across every entry, not just the first', () => {
    const first = particle('temperature', 'celsius')
    const second = particle('temperature', 'humidity')
    const seriesId = second.series[0].id

    const result = removeParticleSeries([first, second], seriesId)

    expect(result).toHaveLength(1)
    expect(result[0].series.map((series) => series.field)).toEqual(['celsius'])
  })
})
