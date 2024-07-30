import { useEngine } from '@/api/engine'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import { defineStore } from 'pinia'
import { QDialogOptions, useQuasar } from 'quasar'

export type Dialogs = ReturnType<typeof useDialogs>

const defaults = {
  class: 'no-shadow',
} as const

export const useDialogs = defineStore('dialogs', () => {
  const engine = useEngine()
  const quasar = useQuasar()

  return {
    show: (options: QDialogOptions) =>
      quasar.dialog({
        ...defaults,
        ...options,
      }),
    delete: (options: QDialogOptions) =>
      quasar.dialog({
        ...defaults,
        title: 'Confirm Deletion',
        ok: {
          color: 'negative',
          label: 'Delete',
        },
        cancel: {
          label: 'Cancel',
          color: 'grey',
          flat: true,
        },
        ...options,
      }),
    changePassword: (userId: string) =>
      quasar.dialog({
        component: ChangePasswordDialog,
        componentProps: {
          engine,
          userId,
        },
      }),
  }
})
