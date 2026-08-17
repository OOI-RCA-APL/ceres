import { describe, expect, it } from 'vitest'

import type { ComponentEffectiveAccess } from '@/api/permissions'
import { groupMatches } from '@/components/c-group-chooser.vue'
import {
  permissionTargetLabel,
  resolveEffectiveAccess,
  sourceLabel,
  targetTypeLabel,
} from '@/permissions'

function entry(overrides: Partial<ComponentEffectiveAccess> = {}): ComponentEffectiveAccess {
  return { address: '@one', level: 'view', source: 'component', ...overrides }
}

describe('naming what a grant applies to', () => {
  it('marks a tag so it cannot be read as a component of the same name', () => {
    expect(permissionTargetLabel({ target_type: 'tag', target: 'sensors' })).toBe('#sensors')
    expect(permissionTargetLabel({ target_type: 'component', target: 'sensors' })).toBe('sensors')
  })

  it('names the whole engine where a grant has no target', () => {
    expect(permissionTargetLabel({ target_type: 'all', target: '' })).toBe('All components')
    expect(targetTypeLabel('all')).toBe('All components')
    expect(targetTypeLabel('component')).toBe('Component')
  })
})

describe('explaining a resolved level', () => {
  it('names the group whose grant conferred it', () => {
    const names = new Map([['g1', 'Operators']])
    expect(sourceLabel(entry({ origin: 'group', group_id: 'g1' }), names)).toBe(
      'Granted on this component, from group "Operators".',
    )
  })

  // A group the caller cannot see still explains the level, and saying so beats naming an ID.
  it('falls back to an unnamed group', () => {
    expect(sourceLabel(entry({ origin: 'group', group_id: 'g9' }), new Map())).toBe(
      'Granted on this component, through a group.',
    )
  })

  it('leaves a direct grant unqualified', () => {
    expect(sourceLabel(entry({ origin: 'user' }), new Map())).toBe('Granted on this component.')
  })
})

describe('resolving effective access', () => {
  it('keeps a component the server reported nothing for', () => {
    const [resolved] = resolveEffectiveAccess(['@one'], [], new Map())
    expect(resolved).toEqual({ address: '@one', level: null, source: null, groupId: null })
  })

  it('carries the group a level came from, for the row to link to', () => {
    const [resolved] = resolveEffectiveAccess(
      ['@one'],
      [entry({ origin: 'group', group_id: 'g1' })],
      new Map([['g1', 'Operators']]),
    )
    expect(resolved?.groupId).toBe('g1')
    expect(resolved?.level).toBe('view')
  })

  it('leaves the group empty on a direct grant', () => {
    const [resolved] = resolveEffectiveAccess(['@one'], [entry({ origin: 'user' })], new Map())
    expect(resolved?.groupId).toBeNull()
  })

  // The engine orders addresses by code point, and anything case-insensitive would reorder them.
  it('orders by code point rather than by locale', () => {
    const resolved = resolveEffectiveAccess(['@b', '@A', '@a'], [], new Map())
    expect(resolved.map((current) => current.address)).toEqual(['@A', '@a', '@b'])
  })
})

describe('narrowing the group chooser', () => {
  const group = { id: 'g1', name: 'Operators', description: 'Runs the plant' }

  it('matches a name or a description, ignoring case', () => {
    expect(groupMatches(group, 'OPER')).toBe(true)
    expect(groupMatches(group, 'plant')).toBe(true)
    expect(groupMatches(group, 'viewers')).toBe(false)
  })

  it('keeps everything while nothing has been typed', () => {
    expect(groupMatches(group, '   ')).toBe(true)
  })
})
