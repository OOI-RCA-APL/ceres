import { merge } from 'lodash-es'
import { defineStore } from 'pinia'
import { QDialogOptions, useQuasar } from 'quasar'

import { useAuth } from '@/api/auth'
import { useEngine } from '@/api/engine'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import WorkspaceDialog from '@/components/WorkspaceDialog.vue'
import { useNavigation } from '@/navigation'
import { WorkspaceData } from '@/workspace'

export type Dialogs = ReturnType<typeof useDialogs>

const defaults = {
  class: ['no-shadow', 'bordered'],
  ok: {
    label: 'Ok',
    color: 'primary',
    unelevated: true,
    autofocus: false,
    'data-autofocus': false,
  },
  cancel: {
    label: 'Cancel',
    color: 'grey-8',
    unelevated: true,
  },
} as const

export const useDialogs = defineStore('dialogs', () => {
  const engine = useEngine()
  const quasar = useQuasar()
  const auth = useAuth()
  const navigation = useNavigation()

  function withDefaults(...options: QDialogOptions[]) {
    return merge({}, defaults, ...options)
  }

  return {
    show: (options: QDialogOptions) => quasar.dialog(withDefaults(options)),
    confirm: (options: QDialogOptions) =>
      quasar.dialog(
        withDefaults(
          {
            title: 'Confirm',
          },
          options
        )
      ),
    delete: (options: QDialogOptions) =>
      quasar.dialog(
        withDefaults(
          {
            title: 'Confirm Deletion',
            ok: {
              label: 'Delete',
              color: 'negative',
            },
            cancel: {
              label: 'Cancel',
            },
          },
          options
        )
      ),
    changePassword: (userId: string) =>
      quasar.dialog(
        withDefaults({
          component: ChangePasswordDialog,
          componentProps: {
            engine,
            userId,
          },
        })
      ),
    workspaceSettings: (workspaceId: string) =>
      quasar.dialog(
        withDefaults({
          component: WorkspaceDialog,
          componentProps: {
            workspaceId,
            action: 'view',
            engine,
            auth,
            navigation,
          },
        })
      ),
    duplicateWorkspace: (workspaceId: string, data?: WorkspaceData) =>
      quasar.dialog(
        withDefaults({
          component: WorkspaceDialog,
          componentProps: {
            workspaceId,
            action: 'duplicate',
            data,
            engine,
            auth,
            navigation,
          },
        })
      ),
  }
})
