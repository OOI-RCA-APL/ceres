import type { ButtonProps } from '@nuxt/ui'
import { defineStore } from 'pinia'

export type Notify = ReturnType<typeof useNotify>

export type NotifyColor = 'primary' | 'success' | 'warning' | 'error' | 'info' | 'neutral'

export type NotifyOptions = Partial<{
  title: string
  description: string
  color: NotifyColor
  icon: string
  duration: number
  actions: ButtonProps[]
}>

/** A toast held open while whatever it reports on is still going. */
export type NotifyHandle = {
  update: (options: NotifyOptions) => void
  close: () => void
}

export const useNotify = defineStore('notify', () => {
  const toast = useToast()

  function show(options: NotifyOptions) {
    toast.add({
      duration: ['warning', 'error'].includes(options.color ?? '') ? 5000 : 1000,
      ...options,
    })
  }

  /** Show a toast that stays until it is closed, for work whose progress it reports. */
  function open(options: NotifyOptions): NotifyHandle {
    const { id } = toast.add({ duration: 0, ...options })

    return {
      // The duration is repeated on every change, since an update replaces it outright rather than
      // leaving it be, and a toast that regains one counts down behind a bar that measures nothing.
      update: (changes) => toast.update(id, { duration: 0, ...changes }),
      close: () => toast.remove(id),
    }
  }

  return {
    show,
    open,
    error: (message: string, options: NotifyOptions = {}) =>
      show({ description: message, color: 'error', icon: 'i-mdi-alert-circle', ...options }),
    info: (message: string, options: NotifyOptions = {}) =>
      show({ description: message, color: 'primary', icon: 'i-mdi-information', ...options }),
    success: (message: string, options: NotifyOptions = {}) =>
      show({ description: message, color: 'success', icon: 'i-mdi-check', ...options }),
    warn: (message: string, options: NotifyOptions = {}) =>
      show({ description: message, color: 'warning', icon: 'i-mdi-alert', ...options }),
  }
})
