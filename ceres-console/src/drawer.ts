import { usePersisted } from '@/persistence'
import { defineStore } from 'pinia'
import { computed } from 'vue'

export const useDrawer = defineStore('drawer', () => {
  const state = usePersisted({
    schema: ({ object, number, boolean }) =>
      object({
        width: number().default(200),
        isOpen: boolean().default(true),
        isShowingUnits: boolean().default(true),
      }),
    methods: [{ type: 'local-storage', key: 'store/drawer' }],
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
    isShowingUnits: computed({
      get: () => state.isShowingUnits,
      set: (value) => (state.isShowingUnits = value),
    }),
  }
})
