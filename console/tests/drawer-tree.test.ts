import { describe, expect, it } from 'vitest'

import { isOnPathTo, treeColumnCenter, treeColumnStart, treeToggleWidth } from '@/drawer'
import { routeComponentAddress } from '@/navigation'

describe('recognizing the branch leading to the open component', () => {
  it('lights the open component itself', () => {
    expect(isOnPathTo('@one.two', '@one.two')).toBe(true)
  })

  it('lights every ancestor above it', () => {
    expect(isOnPathTo('@one.two.three', '@one')).toBe(true)
    expect(isOnPathTo('@one.two.three', '@one.two')).toBe(true)
  })

  // A prefix match alone would light `@one-simulator` whenever `@one` was open.
  it('leaves a sibling whose name merely starts the same way', () => {
    expect(isOnPathTo('@one-simulator', '@one')).toBe(false)
    expect(isOnPathTo('@one.twenty', '@one.two')).toBe(false)
  })

  it('leaves everything when no component is open', () => {
    expect(isOnPathTo(null, '@one')).toBe(false)
  })
})

describe('the tree indent columns', () => {
  it('steps each level out by one column', () => {
    expect(treeColumnCenter(1) - treeColumnCenter(0)).toBe(
      treeColumnCenter(2) - treeColumnCenter(1),
    )
  })

  // A toggle sits in its own column, so the line down the column before it has to pass without
  // touching.
  it('opens a column half a toggle before its center', () => {
    expect(treeColumnCenter(2) - treeColumnStart(2)).toBe(treeToggleWidth / 2)
  })
})

describe('reading the open component off the route', () => {
  it('returns the address the route names', () => {
    expect(routeComponentAddress({ params: { address: '@one.two' } })).toBe('@one.two')
  })

  it('returns null anywhere other than a component page', () => {
    expect(routeComponentAddress({ params: {} })).toBeNull()
    expect(routeComponentAddress({ params: { address: '' } })).toBeNull()
  })
})
