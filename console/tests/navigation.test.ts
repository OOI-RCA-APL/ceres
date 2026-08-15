import { describe, expect, it } from 'vitest'

import { getLoginRedirectPath, userCanAccess } from '@/navigation'

function route(...auth: (boolean | 'admin' | undefined)[]) {
  return { matched: auth.map((value) => ({ meta: { auth: value } })) }
}

const admin = { admin: true }
const member = { admin: false }

describe('deciding who may reach a route', () => {
  it('lets anyone reach a route asking for nothing', () => {
    expect(userCanAccess(null, route(undefined))).toBe(true)
  })

  it('turns away a signed-out visitor where a user is required', () => {
    expect(userCanAccess(null, route(true))).toBe(false)
    expect(userCanAccess(member, route(true))).toBe(true)
  })

  it('admits only an administrator where one is required', () => {
    expect(userCanAccess(member, route('admin'))).toBe(false)
    expect(userCanAccess(admin, route('admin'))).toBe(true)
    expect(userCanAccess(null, route('admin'))).toBe(false)
  })

  // A page nested under an admin section is admin-only however permissive its own entry is,
  // which is what stops a child route reopening what its parent closed.
  it('takes the strictest requirement along the matched chain', () => {
    expect(userCanAccess(member, route(true, 'admin'))).toBe(false)
    expect(userCanAccess(admin, route(true, 'admin'))).toBe(true)
  })
})

describe('sending a visitor to sign in', () => {
  it('carries where they were headed', () => {
    expect(getLoginRedirectPath('/users/1')).toBe('/login?redirect=/users/1')
  })
})
