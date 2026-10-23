import { defineStore } from 'pinia'

import CConfirmDialog, { type ConfirmDialogProps } from '@/components/base/c-confirm-dialog.vue'
import CChangePasswordDialog from '@/components/c-change-password-dialog.vue'
import CFileInfoDialog, { type FileInfoDialogProps } from '@/components/c-file-info-dialog.vue'
import CFileMoveDialog, { type FileMoveDialogProps } from '@/components/c-file-move-dialog.vue'
import CFileNameDialog, { type FileNameDialogProps } from '@/components/c-file-name-dialog.vue'
import CFilterGroupDialog from '@/components/c-filter-group-dialog.vue'
import CWorkspaceDialog from '@/components/c-workspace-dialog.vue'
import CWorkspaceMoveDialog, {
  type WorkspaceMove,
  type WorkspaceMoveDialogProps,
} from '@/components/c-workspace-move-dialog.vue'
import CWorkspaceTransferDialog from '@/components/c-workspace-transfer-dialog.vue'
import type { Workspace, WorkspaceData } from '@/workspace'

export type Dialogs = ReturnType<typeof useDialogs>

/** Follow-up hooks for an opened dialog. A close payload of `false` counts as a cancel, and
anything else lands in `onOk`. */
export type DialogHandle<TPayload = boolean> = {
  onOk(handler: (payload: Exclude<TPayload, false>) => unknown): DialogHandle<TPayload>
  onCancel(handler: () => unknown): DialogHandle<TPayload>
}

/** The payload `handle` closes with, `false` for a cancel. */
export function answer<TPayload>(handle: DialogHandle<TPayload>): Promise<TPayload | false> {
  return new Promise((resolve) => handle.onOk(resolve).onCancel(() => resolve(false)))
}

export const useDialogs = defineStore('dialogs', () => {
  const overlay = useOverlay()
  const confirmDialog = overlay.create(CConfirmDialog)
  const workspaceDialog = overlay.create(CWorkspaceDialog)
  const workspaceTransferDialog = overlay.create(CWorkspaceTransferDialog)
  const workspaceMoveDialog = overlay.create(CWorkspaceMoveDialog)
  const changePasswordDialog = overlay.create(CChangePasswordDialog)
  const filterGroupDialog = overlay.create(CFilterGroupDialog)
  const fileNameDialog = overlay.create(CFileNameDialog)
  const fileInfoDialog = overlay.create(CFileInfoDialog)
  const fileMoveDialog = overlay.create(CFileMoveDialog)

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
    changePassword: (userId: string) => handleOf(changePasswordDialog.open({ userId }).result),
    /** Ask how two filter chips dropped onto each other should be joined. Resolves with the
    operator.
    */
    groupFilters: (labels: [string, string]) => handleOf(filterGroupDialog.open({ labels }).result),
    /** Ask for the name of a file browser entry. Resolves with the trimmed text. */
    fileName: (props: FileNameDialogProps) =>
      handleOf(fileNameDialog.open(props).result) as DialogHandle<string | false>,
    /** Ask for a folder and move file browser entries into it. Resolves with where each entry
    that moved went, by name. */
    moveFiles: (props: FileMoveDialogProps) =>
      handleOf(fileMoveDialog.open(props).result) as DialogHandle<
        ReadonlyMap<string, string[]> | false
      >,
    /** Describe a file browser entry. */
    fileInfo: (props: FileInfoDialogProps) => handleOf(fileInfoDialog.open(props).result),
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
    /** Ask where a workspace goes and whether it moves there or is copied. */
    moveWorkspace: (props: WorkspaceMoveDialogProps) =>
      handleOf(workspaceMoveDialog.open(props).result) as DialogHandle<WorkspaceMove | false>,
    workspaceSettings: (workspaceId: string) =>
      handleOf(workspaceDialog.open({ workspaceId, action: 'view' }).result),
    duplicateWorkspace: (workspaceId: string, data?: WorkspaceData) =>
      handleOf(
        workspaceDialog.open({ workspaceId, action: 'duplicate', data }).result,
      ) as DialogHandle<Workspace | false>,
  }
})
