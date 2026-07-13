import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { useAuth } from '@/api/auth'
import { ComponentAccessLevel, usePermissions } from '@/api/permissions'

export const useAccess = defineStore('access', () => {
  const auth = useAuth()
  const permissions = usePermissions()

  const levels = ref(new Map<string, ComponentAccessLevel>())

  async function refresh() {
    if (auth.user == null) {
      levels.value = new Map()
      return
    }

    const entries = await permissions.getAllEffectiveAccess(auth.user.id)
    levels.value = new Map(entries.map((entry) => [entry.address, entry.level]))
  }

  watch(
    () => auth.user?.id,
    () => {
      void refresh()
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
