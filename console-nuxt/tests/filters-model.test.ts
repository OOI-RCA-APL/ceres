import { describe, expect, it } from 'vitest'

import {
  createBlock,
  createCondition,
  findItem,
  flattenQuery,
  isBlock,
  withFreshIds,
  withGrouped,
  withInserted,
  withMoved,
  withUngrouped,
  withoutItems,
} from '@/filters/model'
import type { FilterQuery } from '@/filters/model'

function ids(query: FilterQuery): string[] {
  return query.map((item) => item.id)
}

describe('the query model', () => {
  it('tells blocks and conditions apart', () => {
    expect(isBlock(createBlock('or'))).toBe(true)
    expect(isBlock(createCondition('contains'))).toBe(false)
  })

  it('flattens blocks before their children', () => {
    const inner = createCondition('contains', 'a')
    const block = createBlock('or', [inner])
    const outer = createCondition('after', 't')

    expect(flattenQuery([block, outer])).toEqual([block, inner, outer])
  })

  it('finds nested items by ID', () => {
    const inner = createCondition('contains', 'a')
    const query = [createBlock('or', [inner])]

    expect(findItem(query, inner.id)).toBe(inner)
    expect(findItem(query, 'missing')).toBeNull()
  })
})

describe('withoutItems', () => {
  it('removes items wherever they nest', () => {
    const inner = createCondition('contains', 'a')
    const keep = createCondition('prefix', 'b')
    const query = [createBlock('and', [inner, keep])]

    const result = withoutItems(query, new Set([inner.id]))

    expect(isBlock(result[0]!) && result[0].children).toEqual([keep])
  })

  it('drops a block emptied by the removal', () => {
    const inner = createCondition('contains', 'a')
    const query = [createBlock('or', [inner]), createCondition('after', 't')]

    const result = withoutItems(query, new Set([inner.id]))

    expect(result).toHaveLength(1)
    expect(isBlock(result[0]!)).toBe(false)
  })
})

describe('withFreshIds', () => {
  it('deep-copies items under new IDs', () => {
    const inner = createCondition('contains', 'a')
    const block = createBlock('or', [inner])

    const [copy] = withFreshIds([block])

    expect(copy!.id).not.toBe(block.id)
    expect(isBlock(copy!) && copy.children[0]!.id).not.toBe(inner.id)
    expect(isBlock(copy!) && copy.children[0]!).toMatchObject({ kind: 'contains', value: 'a' })
  })
})

describe('withInserted', () => {
  it('inserts at the index, clamped to the list', () => {
    const a = createCondition('contains', 'a')
    const b = createCondition('prefix', 'b')
    const c = createCondition('suffix', 'c')

    expect(ids(withInserted([a, b], [c], 1))).toEqual([a.id, c.id, b.id])
    expect(ids(withInserted([a, b], [c], 99))).toEqual([a.id, b.id, c.id])
    expect(ids(withInserted([a, b], [c], -5))).toEqual([c.id, a.id, b.id])
  })
})

describe('withMoved', () => {
  const a = createCondition('contains', 'a')
  const b = createCondition('prefix', 'b')
  const c = createCondition('suffix', 'c')

  it('moves items to the target index, keeping their order', () => {
    expect(ids(withMoved([a, b, c], new Set([a.id]), 3))).toEqual([b.id, c.id, a.id])
    expect(ids(withMoved([a, b, c], new Set([c.id]), 0))).toEqual([c.id, a.id, b.id])
  })

  it('accounts for moving items sitting before the target', () => {
    expect(ids(withMoved([a, b, c], new Set([a.id, b.id]), 3))).toEqual([c.id, a.id, b.id])
  })

  it('returns the query unchanged when nothing matches', () => {
    const query = [a, b, c]
    expect(withMoved(query, new Set(['missing']), 0)).toBe(query)
  })
})

describe('withGrouped and withUngrouped', () => {
  it('groups a selection into one block standing where the first stood', () => {
    const a = createCondition('contains', 'a')
    const b = createCondition('prefix', 'b')
    const c = createCondition('suffix', 'c')

    const result = withGrouped([a, b, c], new Set([a.id, c.id]), 'or')

    expect(result).toHaveLength(2)
    const block = result[0]!
    expect(isBlock(block) && block.op).toBe('or')
    expect(isBlock(block) && ids(block.children)).toEqual([a.id, c.id])
    expect(result[1]!.id).toBe(b.id)
  })

  it('dissolves a block back into its children in place', () => {
    const a = createCondition('contains', 'a')
    const b = createCondition('prefix', 'b')
    const block = createBlock('or', [a, b])
    const after = createCondition('suffix', 'c')

    expect(ids(withUngrouped([block, after], block.id))).toEqual([a.id, b.id, after.id])
  })
})
