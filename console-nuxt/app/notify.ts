import { defineStore } from 'pinia'

export type Notify = ReturnType<typeof useNotify>

export type NotifyColor = 'primary' | 'success' | 'warning' | 'error' | 'info' | 'neutral'

export type NotifyOptions = Partial<{
  title: string
  description: string
  color: NotifyColor
  icon: string
  duration: number
}>

export const useNotify = defineStore('notify', () => {
  const toast = useToast()

  function show(options: NotifyOptions) {
    toast.add({
      duration: ['warning', 'error'].includes(options.color ?? '') ? 5000 : 1000,
      ...options,
    })
  }

  return {
    show,
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
