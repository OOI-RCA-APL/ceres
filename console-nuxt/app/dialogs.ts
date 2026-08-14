import { defineStore } from 'pinia'

import CConfirmDialog, { type ConfirmDialogProps } from '@/components/base/c-confirm-dialog.vue'

export type Dialogs = ReturnType<typeof useDialogs>

export type DialogHandle = {
  onOk(handler: () => unknown): DialogHandle
  onCancel(handler: () => unknown): DialogHandle
}

export const useDialogs = defineStore('dialogs', () => {
  const overlay = useOverlay()
  const confirmDialog = overlay.create(CConfirmDialog)

  function show(options: ConfirmDialogProps): DialogHandle {
    const instance = confirmDialog.open(options)
    const handle: DialogHandle = {
      onOk(handler) {
        void instance.result.then((confirmed) => {
          if (confirmed) {
            handler()
          }
        })
        return handle
      },
      onCancel(handler) {
        void instance.result.then((confirmed) => {
          if (!confirmed) {
            handler()
          }
        })
        return handle
      },
    }
    return handle
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
  }
})
