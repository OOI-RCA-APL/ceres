import { useClient } from '@/api/client'
import { DateTimeModel } from '@/api/shared'
import { User, UserModel, useUsers } from '@/api/users'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import Zod from 'zod'

export type Identity = Zod.infer<typeof IdentityModel>
export const IdentityModel = Zod.object({
  user: UserModel,
  expires: DateTimeModel,
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

  async function changePassword(oldPassword: string, newPassword: string): Promise<User | null> {
    return await client.post('/api/auth/change-password', {
      data: { oldPassword, newPassword },
      parse: UserModel,
    })
  }

  async function assignPassword(userId: string, password: string): Promise<User> {
    return await users.update(userId, { password })
  }

  return {
    login,
    refresh,
    logout,
    changePassword,
    assignPassword,
    identity: computed(() => identity.value),
    user: computed(() => identity.value?.user ?? null),
    isAdmin: computed(() => identity.value?.user?.role === 'admin'),
    isOperator: computed(() => ['operator', 'admin'].includes(identity.value?.user?.role ?? '')),
    isViewer: computed(() => identity.value?.user),
  }
})
