import { describe, expect, it } from 'vitest'

import { compileQuery, hasValue, seedQueryFromFilter } from '@/filters/compile'
import {
  defaultTextKind,
  definitionsFor,
  definitionsForColumn,
  filterDefinitions,
  getFilterDefinition,
  matchDefinitions,
} from '@/filters/definitions'
import { createBlock, createCondition } from '@/filters/model'

describe('the registry', () => {
  it('resolves every declared kind', () => {
    for (const definition of filterDefinitions) {
      expect(getFilterDefinition(definition.kind)).toBe(definition)
    }
  })

  it('returns null for an unknown kind', () => {
    expect(getFilterDefinition('no-such-filter')).toBeNull()
  })

  it('offers each record kind only its own definitions', () => {
    const kinds = definitionsFor('logs').map((definition) => definition.kind)

    expect(kinds).toContain('contains')
    expect(kinds).toContain('min_level')
    expect(kinds).not.toContain('direction')
    expect(kinds).not.toContain('data_contains')
  })

  it('drives header quick filters off the same definitions', () => {
    const timestamp = definitionsForColumn('messages', 'timestamp').map((d) => d.kind)
    expect(timestamp).toEqual([
      'after',
      'before',
      'timespan',
      'after_hour',
      'before_hour',
      'after_minute',
      'before_minute',
    ])

    const data = definitionsForColumn('messages', 'data').map((d) => d.kind)
    expect(data).toEqual(['contains', 'prefix', 'suffix'])

    const level = definitionsForColumn('alerts', 'level').map((d) => d.kind)
    expect(level).toEqual(['level', 'min_level', 'max_level'])
  })

  it('falls back to the record kind text search for free text', () => {
    expect(defaultTextKind('messages')).toBe('contains')
    expect(defaultTextKind('logs')).toBe('contains')
    expect(defaultTextKind('particles')).toBe('data_contains')
    expect(defaultTextKind('alerts')).toBe('data_contains')
  })

  it('ranks prefix matches over substring matches', () => {
    const matched = matchDefinitions(definitionsFor('alerts'), 'lev')

    expect(matched[0]!.kind).toBe('level')
    expect(matched.map((d) => d.kind)).toContain('min_level')
  })

  it('matches through aliases', () => {
    const matched = matchDefinitions(definitionsFor('messages'), 'since')

    expect(matched[0]!.kind).toBe('after')
  })
})

describe('hasValue', () => {
  it('treats null, undefined, and blank text as unset', () => {
    expect(hasValue(null)).toBe(false)
    expect(hasValue(undefined)).toBe(false)
    expect(hasValue('')).toBe(false)
    expect(hasValue('  ')).toBe(false)
    expect(hasValue('x')).toBe(true)
    expect(hasValue(0)).toBe(true)
    expect(hasValue(false)).toBe(true)
  })
})

describe('compileQuery', () => {
  it('merges root conditions into the flat filter', () => {
    const query = [
      createCondition('contains', 'error'),
      createCondition('after', '2026-08-14 00:00:00'),
    ]

    expect(compileQuery(query)).toEqual({
      contains: 'error',
      after: '2026-08-14 00:00:00',
    })
  })

  it('drops conditions with no value yet', () => {
    const query = [createCondition('contains', ''), createCondition('direction', 'send')]

    expect(compileQuery(query)).toEqual({ direction: 'send' })
  })

  it('moves a repeated field into an and term', () => {
    const query = [createCondition('contains', 'a'), createCondition('contains', 'b')]

    expect(compileQuery(query)).toEqual({ contains: 'a', and: [{ contains: 'b' }] })
  })

  it('compiles an or block through an and term with or alternatives', () => {
    const query = [
      createCondition('connection', 'serial'),
      createBlock('or', [
        createCondition('direction', 'send'),
        createCondition('direction', 'receive'),
      ]),
    ]

    expect(compileQuery(query)).toEqual({
      connection: 'serial',
      and: [{ and: [{ direction: 'send' }], or: [{ direction: 'receive' }] }],
    })
  })

  it('compiles an and block as sibling and terms', () => {
    const query = [
      createBlock('and', [createCondition('contains', 'a'), createCondition('prefix', 'b')]),
    ]

    expect(compileQuery(query)).toEqual({
      and: [{ and: [{ contains: 'a' }, { prefix: 'b' }] }],
    })
  })

  it('collapses a one-child block to its child', () => {
    const query = [createBlock('or', [createCondition('contains', 'a')])]

    expect(compileQuery(query)).toEqual({ and: [{ contains: 'a' }] })
  })

  it('drops an empty block entirely', () => {
    const query = [createBlock('or', []), createCondition('contains', 'a')]

    expect(compileQuery(query)).toEqual({ contains: 'a' })
  })

  it('nests blocks recursively', () => {
    const query = [
      createBlock('or', [
        createCondition('level', 'error'),
        createBlock('and', [
          createCondition('level', 'warning'),
          createCondition('contains', 'disk'),
        ]),
      ]),
    ]

    expect(compileQuery(query)).toEqual({
      and: [
        {
          and: [{ level: 'error' }],
          or: [{ and: [{ level: 'warning' }, { contains: 'disk' }] }],
        },
      ],
    })
  })
})

describe('seedQueryFromFilter', () => {
  it('round-trips the old column filters flat output', () => {
    // What the old per-column filter menus stored for each widget kind.
    const cases: [Parameters<typeof seedQueryFromFilter>[1], Record<string, unknown>][] = [
      ['messages', { connection: 'serial', direction: 'send', contains: 'x' }],
      ['particles', { type: 'temperature', data_contains: '7' }],
      ['alerts', { min_level: 'warning', type_contains: 'disk', data_prefix: '{' }],
      ['logs', { max_level: 'info', prefix: 'engine', after_hour: 6 }],
    ]

    for (const [kind, filter] of cases) {
      expect(compileQuery(seedQueryFromFilter(filter, kind))).toEqual(filter)
    }
  })

  it('ignores fields the record kind does not declare', () => {
    const query = seedQueryFromFilter({ direction: 'send', contains: 'x' }, 'logs')

    expect(query.map((item) => ('kind' in item ? item.kind : null))).toEqual(['contains'])
  })

  it('skips unset fields', () => {
    expect(seedQueryFromFilter({ contains: null, prefix: '' }, 'logs')).toEqual([])
  })
})
