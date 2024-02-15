import { DateTimeModel, post } from '@/api/shared'
import { UserModel, useUsers } from '@/api/users'
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

async function postLogin(data: { username: string; password: string }): Promise<Identity> {
  return await post('/api/auth/login', IdentityModel, {
    ...data,
    cookie: getAuthorizationCookieType(),
  })
}

async function postRefresh(): Promise<Identity> {
  return await post('/api/auth/refresh', IdentityModel, { cookie: getAuthorizationCookieType() })
}

async function postLogout(): Promise<Identity> {
  return await post('/api/auth/logout', IdentityModel)
}

async function postChangePassword(data: { oldPassword: string; newPassword: string }) {
  return await post('/api/auth/change-password', UserModel, data)
}

export type AuthStore = ReturnType<typeof useAuth>

export const useAuth = defineStore('auth', () => {
  const identity = ref<Identity | null>(null)
  const users = useUsers()

  async function login(username: string, password: string) {
    try {
      identity.value = await postLogin({
        username,
        password,
      })

      return identity.value
    } catch {
      return null
    }
  }

  async function refresh() {
    try {
      identity.value = await postRefresh()
    } catch (error) {
      identity.value = null
    }

    return identity.value?.user
  }

  async function logout() {
    try {
      await postLogout()
      identity.value = null
    } catch (error) {}
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    try {
      return await postChangePassword({
        oldPassword,
        newPassword,
      })
    } catch (error) {
      return null
    }
  }

  async function assignPassword(userId: string, password: string) {
    try {
      return await users.update(userId, { password })
    } catch (error) {
      return null
    }
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
