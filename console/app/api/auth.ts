import { defineStore } from 'pinia'
import { computed, watch } from 'vue'
import * as z from 'zod'

import { useClient } from '@/api/client'
import { DateTimeModel } from '@/api/shared'
import { type User, UserModel, useUsers } from '@/api/users'
import { type Datetime, duration, utc } from '@/time'

// setTimeout folds its delay into a signed 32 bit integer, so anything past ~24.8 days overflows
// and fires immediately. A 30 day token scheduled naively therefore refreshes in a tight loop.
// Waking daily is far inside that limit, and an early refresh just schedules the next one.
const maxRefreshDelayMs = duration(1, 'day').asMilliseconds()

/** Milliseconds to wait before refreshing an identity that expires at `expires`.

Aimed a minute before the expiry, never negative, and capped a day out so the delay stays inside
what `setTimeout` can count to.
*/
export function refreshDelayMs(expires: string, now: Datetime = utc()): number {
  const delay = duration(utc(expires).subtract(1, 'minute').diff(now)).asMilliseconds()
  return Math.min(Math.max(delay, 0), maxRefreshDelayMs)
}

export type Identity = z.infer<typeof IdentityModel>
export const IdentityModel = z.object({
  user: UserModel,
  expires: DateTimeModel,
  token: z.string(),
  impersonated_by: z.string().nullish(),
})

export const AuthFeaturesModel = z.object({
  impersonate: z.boolean(),
})

function getAuthorizationCookieType() {
  if (location.protocol.startsWith('https')) {
    return 'secure'
  }

  return 'insecure'
}

export type AuthStore = ReturnType<typeof useAuth>

export const useAuth = defineStore('auth', () => {
  const client = useClient()
  let identity = $ref<Identity | null>(null)
  let features = $ref<z.infer<typeof AuthFeaturesModel> | null>(null)
  const users = useUsers()

  async function login(username: string, password: string): Promise<Identity> {
    identity = await client.post('/api/auth/login', {
      data: { username, password, cookie: getAuthorizationCookieType() },
      parse: IdentityModel,
    })

    return identity
  }

  async function refresh(): Promise<Identity | null> {
    try {
      identity = await client.post('/api/auth/refresh', {
        data: { cookie: getAuthorizationCookieType() },
        parse: IdentityModel,
      })
      return identity
    } catch {
      identity = null
      return null
    }
  }

  async function logout(): Promise<Identity> {
    const result = await client.post('/api/auth/logout', {
      parse: IdentityModel,
    })

    identity = null
    return result
  }

  // The token the admin held before impersonating. Stopping replays it so they land back on their
  // own account without a password, and without any route accepting a call from a user who is not
  // an admin.
  //
  // Held in session storage rather than in memory, because the impersonated identity is not an
  // admin and so cannot start over. Losing this on a page reload would strand the admin as
  // somebody else with nothing but a fresh login to get out. Session storage is per tab and goes
  // away with it, and the equivalent token is already sitting in a cookie either way.
  const impersonationKey = 'ceres.impersonation.previous-token'
  let tokenBeforeImpersonating = $ref<string | null>(sessionStorage.getItem(impersonationKey))

  watch(
    () => tokenBeforeImpersonating,
    (token) => {
      if (token == null) {
        sessionStorage.removeItem(impersonationKey)
      } else {
        sessionStorage.setItem(impersonationKey, token)
      }
    },
  )

  async function loadFeatures() {
    features = await client.get('/api/auth/features', { parse: AuthFeaturesModel })
  }

  async function impersonate(userId: string): Promise<Identity> {
    const previous = tokenBeforeImpersonating ?? identity?.token ?? null
    identity = await client.post('/api/auth/impersonate', {
      data: { user_id: userId, cookie: getAuthorizationCookieType() },
      parse: IdentityModel,
    })

    tokenBeforeImpersonating = previous
    return identity
  }

  /** Return to the account that started impersonating, or sign out if that is no longer possible.
   *
   * The impersonated identity is not an administrator and cannot start over, so losing the stashed
   * token would otherwise be a dead end. Signing out is the honest fallback, since the way back to
   * an administrator is then a password.
   */
  async function stopImpersonating(): Promise<Identity | null> {
    const token = tokenBeforeImpersonating
    tokenBeforeImpersonating = null

    if (token == null) {
      await logout()
      return null
    }

    identity = await client.post('/api/auth/refresh', {
      data: { cookie: getAuthorizationCookieType() },
      init: {
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      },
      parse: IdentityModel,
    })

    return identity
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<User | null> {
    try {
      return await client.post('/api/auth/change-password', {
        data: { old_password: oldPassword, new_password: newPassword },
        parse: UserModel,
      })
    } catch (error) {
      console.error(error)
      return null
    }
  }

  async function assignPassword(userId: string, password: string): Promise<User | null> {
    try {
      return await users.update(userId, { password })
    } catch (error) {
      console.error(error)
      return null
    }
  }

  return {
    login,
    refresh,
    logout,
    loadFeatures,
    impersonate,
    stopImpersonating,
    changePassword,
    assignPassword,
    identity: computed(() => identity),
    user: computed(() => identity?.user ?? null),
    isAdmin: computed(() => identity?.user?.admin ?? false),
    isViewer: computed(() => identity?.user),
    canImpersonate: computed(() => features?.impersonate === true),
    // Taken from the identity rather than from the stashed token, because the server is what knows
    // this and the stash is only what makes returning cheap. Reading the stash instead would hide
    // the way out precisely when the stash is the thing that went missing.
    isImpersonating: computed(() => identity?.impersonated_by != null),
  }
})
