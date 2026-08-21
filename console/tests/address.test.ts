import { describe, expect, it } from 'vitest'

import { AddressSelector } from '@/api/address'

/** Whether the selector picks out each address, as a readable list. */
function selected(selector: string, addresses: string[]): string[] {
  const parsed = new AddressSelector(selector)
  return addresses.filter((address) => parsed.selects(address))
}

const everything = ['~', '@abc', '@abc.cde', '@abc.cde.efg', '@cde']

describe('AddressSelector.selects', () => {
  it('takes a literal address alone', () => {
    expect(selected('@abc', everything)).toEqual(['@abc'])
  })

  it('takes a component and its descendants for all', () => {
    expect(selected('@abc:all', everything)).toEqual(['@abc', '@abc.cde', '@abc.cde.efg'])
  })

  it('leaves the component out for descendants', () => {
    expect(selected('@abc:descendants', everything)).toEqual(['@abc.cde', '@abc.cde.efg'])
  })

  it('reaches one level down for children', () => {
    expect(selected('@abc:children', everything)).toEqual(['@abc.cde'])
  })

  it('reaches every component but the engine for the bare wildcard', () => {
    expect(selected('@:all', everything)).toEqual(['@abc', '@abc.cde', '@abc.cde.efg', '@cde'])
    expect(selected('@:descendants', everything)).toEqual([
      '@abc',
      '@abc.cde',
      '@abc.cde.efg',
      '@cde',
    ])
  })

  it('reaches the top level alone for the wildcard children', () => {
    expect(selected('@:children', everything)).toEqual(['@abc', '@cde'])
  })

  it('reaches everything including the engine for the engine wildcard', () => {
    expect(selected('~:all', everything)).toEqual(everything)
    expect(selected('~:descendants', everything)).toEqual([
      '@abc',
      '@abc.cde',
      '@abc.cde.efg',
      '@cde',
    ])
  })

  it('takes the engine alone when named', () => {
    expect(selected('~', everything)).toEqual(['~'])
  })

  it('takes any segment of several', () => {
    expect(selected('@cde|@abc:children', everything)).toEqual(['@abc.cde', '@cde'])
  })

  it('does not mistake a shared prefix for a descendant', () => {
    expect(selected('@abc:all', ['@abcd', '@abcd.efg'])).toEqual([])
  })
})
