import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import Zod from 'zod'

import { useClient } from '@/api/client'
import { DateTimeModel } from '@/api/shared'
import { User, UserModel, useUsers } from '@/api/users'

export type Identity = Zod.infer<typeof IdentityModel>
export const IdentityModel = Zod.object({
  user: UserModel,
  expires: DateTimeModel,
  token: Zod.string(),
  switched_from: Zod.string().nullish(),
})

export const AuthFeaturesModel = Zod.object({
  user_switching: Zod.boolean(),
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
  const identity = ref<Identity | null>(null)
  const features = ref<Zod.infer<typeof AuthFeaturesModel> | null>(null)
  const users = useUsers()

  async function login(username: string, password: string): Promise<Identity> {
    identity.value = await client.post('/api/auth/login', {
      data: { username, password, cookie: getAuthorizationCookieType() },
      parse: IdentityModel,
    })

    return identity.value
  }

  async function refresh(): Promise<Identity | null> {
    try {
      identity.value = await client.post('/api/auth/refresh', {
        data: { cookie: getAuthorizationCookieType() },
        parse: IdentityModel,
      })
      return identity.value
    } catch (error) {
      identity.value = null
      return null
    }
  }

  async function logout(): Promise<Identity> {
    const result = await client.post('/api/auth/logout', {
      parse: IdentityModel,
    })

    identity.value = null
    return result
  }

  // The token the current admin held before switching, kept only in memory for as long as the
  // switch lasts. Returning replays it so the admin lands back on their own account without a
  // password, and without any route accepting a switch from a user who is not an admin.
  const tokenBeforeSwitch = ref<string | null>(null)

  async function loadFeatures() {
    features.value = await client.get('/api/auth/features', { parse: AuthFeaturesModel })
  }

  async function switchUser(userId: string): Promise<Identity> {
    const previous = tokenBeforeSwitch.value ?? identity.value?.token ?? null
    identity.value = await client.post('/api/auth/switch', {
      data: { user_id: userId, cookie: getAuthorizationCookieType() },
      parse: IdentityModel,
    })

    tokenBeforeSwitch.value = previous
    return identity.value
  }

  async function returnFromSwitch(): Promise<Identity | null> {
    const token = tokenBeforeSwitch.value
    if (token == null) {
      return null
    }

    identity.value = await client.post('/api/auth/refresh', {
      data: { cookie: getAuthorizationCookieType() },
      init: {
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      },
      parse: IdentityModel,
    })

    tokenBeforeSwitch.value = null
    return identity.value
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
    switchUser,
    returnFromSwitch,
    changePassword,
    assignPassword,
    identity: computed(() => identity.value),
    user: computed(() => identity.value?.user ?? null),
    isAdmin: computed(() => identity.value?.user?.admin ?? false),
    isViewer: computed(() => identity.value?.user),
    canSwitchUser: computed(() => features.value?.user_switching === true),
    // A switch is in progress while the console still holds the admin's own token, which is what
    // makes returning possible.
    isSwitched: computed(() => tokenBeforeSwitch.value != null),
  }
})
