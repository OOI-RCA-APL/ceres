import { describe, expect, it } from 'vitest'

import { ParticleTypeInfoModel } from '@/api/components'
import { filterParticleEntries, particleTypeEntries } from '@/particle-types'

/** A type carrying `value` and `count`, stamped by `connections`. */
function declared(type: string, ...connections: string[]) {
  return ParticleTypeInfoModel.parse({
    type,
    fields: [
      { name: 'value', schema: { type: 'number' } },
      { name: 'count', schema: { type: 'integer' } },
    ],
    connections,
  })
}

const label = (connection: string) => `Port ${connection}`

describe('particleTypeEntries', () => {
  it('gives each connection of a type its own labeled entry', () => {
    const entries = particleTypeEntries([declared('pressure', 'one', 'two')], label)

    expect(entries.map((entry) => [entry.connection, entry.connectionLabel])).toEqual([
      ['one', 'Port one'],
      ['two', 'Port two'],
    ])
  })

  it('keeps one connection without a label, and none as every connection', () => {
    const entries = particleTypeEntries([declared('pressure', 'one'), declared('depth')], label)

    expect(entries.map((entry) => [entry.connection, entry.connectionLabel])).toEqual([
      ['one', null],
      [null, null],
    ])
  })
})

describe('filterParticleEntries', () => {
  const entries = particleTypeEntries(
    [declared('pressure', 'one', 'two'), declared('depth')],
    label,
  )

  function shown(search: string) {
    return filterParticleEntries('@gauge', entries, search).map((entry) => [
      entry.connection,
      entry.fields.map((field) => field.name),
    ])
  }

  it('matches every word across connection, type and field', () => {
    expect(shown('port two cou')).toEqual([['two', ['count']]])
  })

  it('keeps every field of an entry the search matches without them', () => {
    expect(shown('PRESSURE one')).toEqual([['one', ['value', 'count']]])
  })

  it('matches the address', () => {
    expect(shown('gauge')).toHaveLength(3)
  })
})
