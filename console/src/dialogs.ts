import { useAuth } from '@/auth'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import { QDialogOptions, useQuasar } from 'quasar'

export function useDialogs() {
  const auth = useAuth()
  const quasar = useQuasar()

  return {
    show: (options: QDialogOptions) => quasar.dialog(options),
    delete: (options: QDialogOptions) =>
      quasar.dialog({
        title: 'Confirm Deletion',
        ok: {
          color: 'negative',
          flat: true,
          label: 'Delete',
        },
        cancel: {
          flat: true,
          label: 'Cancel',
          color: 'grey',
        },
        ...options,
      }),

    changePassword: (userId: string) =>
      quasar.dialog({
        component: ChangePasswordDialog,
        componentProps: {
          auth,
          userId,
        },
      }),
  }
}

export type Dialogs = ReturnType<typeof useDialogs>
