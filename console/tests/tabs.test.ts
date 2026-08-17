import { describe, expect, it } from 'vitest'

import { resolveTabs, type TabSet } from '@/tabs'

type Item = { id: string }

function items(...ids: string[]): Item[] {
  return ids.map((id) => ({ id }))
}

function identify(item: Item): string {
  return item.id
}

function set(open: string[] = [], closed: string[] = []): TabSet {
  return { open, closed }
}

function shown(defaults: Item[], tabSet: TabSet, pool?: Item[]): string[] {
  return resolveTabs(defaults, tabSet, identify, pool).map(identify)
}

describe('resolveTabs', () => {
  it('shows the defaults untouched for an empty set', () => {
    expect(shown(items('a', 'b'), set())).toEqual(['a', 'b'])
  })

  it('puts opened tabs first, in the order they were opened', () => {
    expect(shown(items('a', 'b'), set(['b']))).toEqual(['b', 'a'])
  })

  it('drops closed defaults', () => {
    expect(shown(items('a', 'b'), set([], ['a']))).toEqual(['b'])
  })

  it('never shows one tab twice, however the set names it', () => {
    expect(shown(items('a'), set(['a']))).toEqual(['a'])
  })

  it('resolves opened identifiers against the pool, not only the defaults', () => {
    expect(shown(items('a'), set(['x']), items('a', 'x'))).toEqual(['x', 'a'])
  })

  it('silently drops an identifier nothing resolves', () => {
    expect(shown(items('a'), set(['gone']))).toEqual(['a'])
  })

  it('lets closed win only over defaults, an explicit open still shows', () => {
    expect(shown(items('a', 'b'), set(['a'], ['b']))).toEqual(['a'])
  })
})
