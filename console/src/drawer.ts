import { Address } from '@/api/address'
import { usePersisted } from '@/persistence'
import { defineStore } from 'pinia'
import { computed } from 'vue'

export const useDrawer = defineStore('drawer', () => {
  const state = usePersisted({
    schema: ({ object, array, number, string, boolean }) =>
      object({
        width: number().default(200),
        isOpen: boolean().default(true),
        collapsed: array(string().transform(Address.parse)).default(() => []),
      }),
    methods: [{ type: 'local-storage', key: ['store', 'drawer'] }],
  })

  return {
    width: computed({
      get: () => state.width,
      set: (value) => (state.width = value),
    }),
    isOpen: computed({
      get: () => state.isOpen,
      set: (value) => (state.isOpen = value),
    }),
    collapsed: computed({
      get: () => state.collapsed,
      set: (value) => (state.collapsed = value),
    }),
    toggle: () => (state.isOpen = !state.isOpen),
  }
})
