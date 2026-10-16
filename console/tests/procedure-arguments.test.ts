import { beforeEach, describe, expect, it } from 'vitest'

import { Address } from '@/api/address'
import { rememberArguments, rememberedArguments } from '@/procedure-arguments'

const abc = Address.parse('@abc')
const abcd = Address.parse('@abcd')

describe('arguments remembered per procedure', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('recalls what was last entered for the same component and procedure', () => {
    rememberArguments(abc, 'read', { unit: 'F' })
    expect(rememberedArguments(abc, 'read')).toEqual({ unit: 'F' })
  })

  it('keeps each component and procedure apart', () => {
    rememberArguments(abc, 'read', { unit: 'F' })
    expect(rememberedArguments(abc, 'write')).toBeUndefined()
    expect(rememberedArguments(abcd, 'read')).toBeUndefined()
  })
})
