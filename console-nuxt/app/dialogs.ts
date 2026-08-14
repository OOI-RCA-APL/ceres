import { defineStore } from 'pinia'

import CConfirmDialog, { type ConfirmDialogProps } from '@/components/base/c-confirm-dialog.vue'
import CWorkspaceDialog from '@/components/c-workspace-dialog.vue'
import CWorkspaceTransferDialog from '@/components/c-workspace-transfer-dialog.vue'
import type { Workspace, WorkspaceData } from '@/workspace'

export type Dialogs = ReturnType<typeof useDialogs>

/** Follow-up hooks for an opened dialog. A close payload of `false` counts as a cancel, and
anything else lands in `onOk`. */
export type DialogHandle<TPayload = boolean> = {
  onOk(handler: (payload: Exclude<TPayload, false>) => unknown): DialogHandle<TPayload>
  onCancel(handler: () => unknown): DialogHandle<TPayload>
}

export const useDialogs = defineStore('dialogs', () => {
  const overlay = useOverlay()
  const confirmDialog = overlay.create(CConfirmDialog)
  const workspaceDialog = overlay.create(CWorkspaceDialog)
  const workspaceTransferDialog = overlay.create(CWorkspaceTransferDialog)

  function handleOf<TPayload>(result: Promise<TPayload>): DialogHandle<TPayload> {
    const handle: DialogHandle<TPayload> = {
      onOk(handler) {
        void result.then((payload) => {
          if (payload !== false) {
            handler(payload as Exclude<TPayload, false>)
          }
        })
        return handle
      },
      onCancel(handler) {
        void result.then((payload) => {
          if (payload === false) {
            handler()
          }
        })
        return handle
      },
    }
    return handle
  }

  function show(options: ConfirmDialogProps): DialogHandle<boolean> {
    return handleOf(confirmDialog.open(options).result)
  }

  return {
    show,
    confirm: (options: ConfirmDialogProps) => show({ title: 'Confirm', ...options }),
    delete: (options: ConfirmDialogProps) =>
      show({
        title: 'Confirm Deletion',
        okLabel: 'Delete',
        okColor: 'error',
        ...options,
      }),
    /** Create a workspace on `scope`. `isPrivate` presets the choice for a caller that already
    knows which kind is wanted, such as one adding to a named group.
    */
    createWorkspace: (scope?: string, isPrivate?: boolean) =>
      handleOf(workspaceDialog.open({ action: 'create', scope, isPrivate }).result) as DialogHandle<
        Workspace | false
      >,
    /** Ask whether to move or copy a workspace between shared and private. Resolves with the
    chosen mode.
    */
    transferWorkspace: (workspace: Workspace, to: 'shared' | 'private', canMove: boolean) =>
      handleOf(workspaceTransferDialog.open({ workspace, to, canMove }).result),
    workspaceSettings: (workspaceId: string) =>
      handleOf(workspaceDialog.open({ workspaceId, action: 'view' }).result),
    duplicateWorkspace: (workspaceId: string, data?: WorkspaceData) =>
      handleOf(
        workspaceDialog.open({ workspaceId, action: 'duplicate', data }).result,
      ) as DialogHandle<Workspace | false>,
  }
})
