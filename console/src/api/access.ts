import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { useAuth } from '@/api/auth'
import { ComponentAccessLevel, usePermissions } from '@/api/permissions'
import { useNotify } from '@/notify'

export const useAccess = defineStore('access', () => {
  const auth = useAuth()
  const permissions = usePermissions()
  const notify = useNotify()

  const levels = ref(new Map<string, ComponentAccessLevel>())

  async function refresh() {
    if (auth.user == null) {
      levels.value = new Map()
      return
    }

    // Capture the requesting user so a response that resolves after the user has
    // logged out or switched accounts cannot overwrite the map for the wrong session.
    const userId = auth.user.id
    const entries = await permissions.getAllEffectiveAccess(userId)
    if (auth.user?.id !== userId) {
      return
    }

    levels.value = new Map(entries.map((entry) => [entry.address, entry.level]))
  }

  watch(
    () => auth.user?.id,
    () => {
      refresh().catch((error) => {
        console.error(error)
        notify.error('Failed to load component access.')
      })
    },
    { immediate: true }
  )

  function levelFor(address: string): ComponentAccessLevel | null {
    if (auth.user?.admin) {
      return 'manage'
    }

    return levels.value.get(address) ?? null
  }

  function canOperate(address: string): boolean {
    const level = levelFor(address)
    return level === 'operate' || level === 'manage'
  }

  function canManage(address: string): boolean {
    return levelFor(address) === 'manage'
  }

  return { refresh, levelFor, canOperate, canManage }
})
