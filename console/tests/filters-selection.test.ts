import { beforeEach, describe, expect, it } from 'vitest'

import type { RecordKind } from '@/filters/definitions'
import { createCondition, isBlock } from '@/filters/model'
import type { FilterQuery } from '@/filters/model'
import { createFilterSelection } from '@/filters/selection'
import type { FilterSelection } from '@/filters/selection'

let query: FilterQuery
let selection: FilterSelection
let recordKind: RecordKind

const a = createCondition('contains', 'a')
const b = createCondition('prefix', 'b')
const c = createCondition('suffix', 'c')

beforeEach(() => {
  query = [a, b, c]
  recordKind = 'messages'
  selection = createFilterSelection({
    query: () => query,
    recordKind: () => recordKind,
    onUpdate: (updated) => {
      query = updated
    },
  })
})

describe('select', () => {
  it('replaces by default', () => {
    selection.select(a.id)
    selection.select(b.id)

    expect([...selection.selectedIds.value]).toEqual([b.id])
  })

  it('toggles membership', () => {
    selection.select(a.id)
    selection.select(b.id, 'toggle')
    expect(selection.isSelected(a.id)).toBe(true)
    expect(selection.isSelected(b.id)).toBe(true)

    selection.select(a.id, 'toggle')
    expect(selection.isSelected(a.id)).toBe(false)
  })

  it('extends across the root order from the anchor', () => {
    selection.select(a.id)
    selection.select(c.id, 'extend')

    expect(selection.isSelected(a.id)).toBe(true)
    expect(selection.isSelected(b.id)).toBe(true)
    expect(selection.isSelected(c.id)).toBe(true)
  })

  it('extends backwards too', () => {
    selection.select(c.id)
    selection.select(a.id, 'extend')

    expect(selection.selectedIds.value.size).toBe(3)
  })

  it('ensureSelected keeps an existing multi-selection', () => {
    selection.select(a.id)
    selection.select(b.id, 'toggle')
    selection.ensureSelected(a.id)

    expect(selection.selectedIds.value.size).toBe(2)

    selection.ensureSelected(c.id)
    expect([...selection.selectedIds.value]).toEqual([c.id])
  })
})

describe('remove, copy, and paste', () => {
  it('removes the selection and clears it', () => {
    selection.select(a.id)
    selection.select(b.id, 'toggle')
    selection.removeSelected()

    expect(query.map((item) => item.id)).toEqual([c.id])
    expect(selection.selectedIds.value.size).toBe(0)
  })

  it('pastes copies under fresh IDs at the selection, and selects them', () => {
    selection.select(b.id)
    selection.copySelected()
    selection.paste()

    expect(query).toHaveLength(4)
    const pasted = query[1]!
    expect(pasted.id).not.toBe(b.id)
    expect(pasted).toMatchObject({ kind: 'prefix', value: 'b' })
    expect(selection.isSelected(pasted.id)).toBe(true)
  })

  it('pastes at the end with nothing selected', () => {
    selection.select(a.id)
    selection.copySelected()
    selection.clear()
    selection.paste()

    expect(query).toHaveLength(4)
    expect(query[3]).toMatchObject({ kind: 'contains', value: 'a' })
  })

  it('refuses a paste into a bar over another record kind', () => {
    selection.select(a.id)
    selection.copySelected()
    recordKind = 'particles'

    expect(selection.canPaste()).toBe(false)
    selection.paste()
    expect(query).toHaveLength(3)
  })

  it('pastes a multi-selection as a unit at an index', () => {
    selection.select(a.id)
    selection.select(b.id, 'toggle')
    selection.copySelected()
    selection.paste(0)

    expect(query).toHaveLength(5)
    expect(query[0]).toMatchObject({ kind: 'contains' })
    expect(query[1]).toMatchObject({ kind: 'prefix' })
  })

  it('cut removes what it copied', () => {
    selection.select(b.id)
    selection.cutSelected()

    expect(query.map((item) => item.id)).toEqual([a.id, c.id])

    selection.paste()
    expect(query[2]).toMatchObject({ kind: 'prefix', value: 'b' })
  })
})

describe('move and group', () => {
  it('moves the selection as a unit', () => {
    selection.select(a.id)
    selection.select(b.id, 'toggle')
    selection.moveSelected(3)

    expect(query.map((item) => item.id)).toEqual([c.id, a.id, b.id])
  })

  it('groups the selection into a block and ungroups it back', () => {
    selection.select(a.id)
    selection.select(c.id, 'toggle')
    selection.groupSelected('or')

    expect(query).toHaveLength(2)
    const block = query[0]!
    expect(isBlock(block) && block.op).toBe('or')

    selection.ungroup(block.id)
    expect(query.map((item) => item.id)).toEqual([a.id, c.id, b.id])
  })
})
