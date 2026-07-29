import { merge } from 'lodash-es'
import { defineStore } from 'pinia'
import { QDialogOptions, useQuasar } from 'quasar'

import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'
import WorkspaceDialog from '@/components/WorkspaceDialog.vue'
import WorkspaceTransferDialog from '@/components/WorkspaceTransferDialog.vue'
import { Workspace, WorkspaceData } from '@/workspace'

export type Dialogs = ReturnType<typeof useDialogs>

const defaults = {
  class: ['no-shadow', 'bordered'],
  ok: {
    label: 'Ok',
    color: 'primary',
    unelevated: true,
    class: 'col-3',
  },
  cancel: {
    label: 'Cancel',
    color: 'grey-8',
    class: 'col-3',
    unelevated: true,
  },
} as const

export const useDialogs = defineStore('dialogs', () => {
  const quasar = useQuasar()

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
            userId,
          },
        })
      ),
    /** Create a workspace on `scope`. `isPrivate` presets the choice for a caller that already
    knows which kind is wanted, such as one adding to a named group.
    */
    createWorkspace: (scope?: string, isPrivate?: boolean) =>
      quasar.dialog(
        withDefaults({
          component: WorkspaceDialog,
          componentProps: {
            action: 'create',
            scope,
            isPrivate,
          },
        })
      ),
    /** Ask whether to move or copy a workspace between shared and private. Resolves with the
    chosen mode.
    */
    transferWorkspace: (workspace: Workspace, to: 'shared' | 'private', canMove: boolean) =>
      quasar.dialog(
        withDefaults({
          component: WorkspaceTransferDialog,
          componentProps: {
            workspace,
            to,
            canMove,
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
          },
        })
      ),
  }
})
