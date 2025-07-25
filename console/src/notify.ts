import { defineStore } from 'pinia'
import { useQuasar } from 'quasar'

import { getForegroundColor } from '@/colors'
import icons from '@/icons'

export type Notify = ReturnType<typeof useNotify>

export const useNotify = defineStore('notify', () => {
  const quasar = useQuasar()
  type NotifyOptions = Exclude<Parameters<typeof quasar.notify>[0], string>

  function applyDefaults(options: NotifyOptions): NotifyOptions {
    return {
      textColor: options.color != null ? getForegroundColor(options.color) : undefined,
      badgeColor: options.color != null ? options.color : undefined,
      timeout: ['warning', 'negative'].includes(options.color ?? '') ? 5000 : 1000,
      closeBtn: false,
      actions: [
        {
          icon: icons.close,
          textColor: options.color != null ? getForegroundColor(options.color) : undefined,
          color: options.color,
          dense: true,
          size: '13px',
          round: true,
          class: 'faded-hover',
        },
      ],
      ...options,
    }
  }

  return {
    show: (options: NotifyOptions) =>
      quasar.notify(
        applyDefaults({
          ...options,
        })
      ),
    error: (message: string, options: NotifyOptions = {}) =>
      quasar.notify(
        applyDefaults({
          message,
          color: 'negative',
          icon: 'error',
          ...options,
        })
      ),
    info: (message: string, options: NotifyOptions = {}) =>
      quasar.notify(
        applyDefaults({
          message,
          color: 'primary',
          icon: 'info',
          ...options,
        })
      ),
    success: (message: string, options: NotifyOptions = {}) =>
      quasar.notify(
        applyDefaults({
          message,
          color: 'positive',
          icon: 'check',
          ...options,
        })
      ),
    warn: (message: string, options: NotifyOptions = {}) =>
      quasar.notify(
        applyDefaults({
          message,
          color: 'warning',
          icon: 'warning',
          ...options,
        })
      ),
  }
})
