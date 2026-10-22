import { describe, expect, it } from 'vitest'

import { createRowSelection } from '@/row-selection'

function selection(ids = ['a', 'b', 'c', 'd']) {
  return createRowSelection({ ids: () => ids })
}

describe('createRowSelection', () => {
  it('steps forward from the first row and back from the last when nothing is chosen', () => {
    expect(selection().step(1)).toBe('a')
    expect(selection().step(-1)).toBe('d')
  })

  it('steps on from the row last chosen and stops at the end', () => {
    const rows = selection()
    rows.select('b')
    expect(rows.step(1)).toBe('c')
    expect(rows.step(1)).toBe('d')
    expect(rows.step(1)).toBe('d')
    expect(rows.selected()).toEqual(['d'])
  })

  it('extends from the anchor as it steps', () => {
    const rows = selection()
    rows.select('b')
    rows.step(1, 'extend')
    rows.step(1, 'extend')
    expect(rows.selected()).toEqual(['b', 'c', 'd'])
    rows.step(-1, 'extend')
    expect(rows.selected()).toEqual(['b', 'c'])
  })

  it('steps on from the first row of a replaced selection', () => {
    const rows = selection()
    rows.replace(['a', 'b', 'c', 'd'])
    expect(rows.step(1)).toBe('b')
    expect(rows.selected()).toEqual(['b'])
  })

  it('starts over once cleared', () => {
    const rows = selection()
    rows.select('c')
    rows.clear()
    expect(rows.step(1)).toBe('a')
  })

  it('steps nowhere in an empty list', () => {
    expect(selection([]).step(1)).toBeNull()
  })
})
