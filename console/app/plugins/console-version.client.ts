import { useEventListener } from '@vueuse/core'

import { useConsoleVersion } from '@/console-version'

// Nuxt checks the served build hourly and reloads only on the next navigation, which a dashboard
// left open never makes. The app shows a reload prompt instead, and checks again whenever the page
// becomes visible or its streams reconnect, an engine restart being when an upgrade lands.
export default defineNuxtPlugin((nuxtApp) => {
  const { app } = useRuntimeConfig()
  const consoleVersion = useConsoleVersion()
  const assets = `${app.baseURL}/${app.buildAssetsDir}`.replace(/\/+/g, '/')
  consoleVersion.start(app.buildId, `${assets}builds/latest.json`)

  nuxtApp.hook('app:manifest:update', (meta) => {
    if (meta != null) {
      consoleVersion.learn(meta.id)
    }
  })

  useEventListener(document, 'visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      void consoleVersion.check()
    }
  })
})
