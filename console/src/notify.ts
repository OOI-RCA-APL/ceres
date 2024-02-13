import { getForegroundColor } from '@/colors'
import { useQuasar } from 'quasar'
import icons from '@/icons'

export function useNotify() {
  const quasar = useQuasar()

  type NotifyOptions = Exclude<Parameters<typeof quasar.notify>[0], string>

  function applyDefaults(options: NotifyOptions): NotifyOptions {
    return {
      textColor: options.color != null ? getForegroundColor(options.color) : undefined,
      badgeColor: options.color != null ? options.color : undefined,
      actions: [
        {
          icon: icons.close,
          color: options.color != null ? getForegroundColor(options.color) : undefined,
          dense: true,
          round: true,
          flat: true,
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
}
