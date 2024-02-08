import { Identity } from '@/api/models'
import { patchUser, postChangePassword, postLogin, postLogout, postRefresh } from '@/api/operations'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type AuthStore = ReturnType<typeof useAuth>

export const useAuth = defineStore('auth', () => {
  const identity = ref<Identity | null>(null)

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
      return await patchUser(userId, { password })
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
