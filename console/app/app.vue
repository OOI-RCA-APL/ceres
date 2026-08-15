<script lang="ts" setup>
import { useEventListener } from '@vueuse/core'
import { computed, watchEffect } from 'vue'

import { refreshDelayMs } from '@/api/auth'
import { useEngine } from '@/api/engine'
import constants from '@/constants'
import { getLoginRedirectPath, useNavigation, userCanAccess } from '@/navigation'
import { useNotify } from '@/notify'

const engine = useEngine()
const navigation = useNavigation()
const notify = useNotify()

useHead({
  title: computed(() => engine.config.console?.title ?? constants.defaultTitle),
})

// If we are logged in, set a timeout to do a refresh just before the access token expires. The
// delay is clamped by `refreshDelayMs`, since a long-lived token would otherwise overflow
// setTimeout and fire immediately, refreshing in a tight loop.
watchEffect((onInvalidate) => {
  if (engine.auth.identity?.expires == null) {
    return
  }

  const timeout = setTimeout(() => {
    void engine.auth.refresh()
  }, refreshDelayMs(engine.auth.identity.expires))

  onInvalidate(() => {
    clearTimeout(timeout)
  })
})

useEventListener(window, 'focus', () => {
  const wasLoggedIn = engine.auth.user != null
  void engine.auth.refresh().then(() => {
    if (wasLoggedIn && engine.auth.user == null) {
      notify.warn('You have been signed out due to inactivity.')
    }

    if (!userCanAccess(engine.auth.user, navigation.route)) {
      void navigation.replace(getLoginRedirectPath(navigation.route.fullPath))
      notify.warn('You do not have access to that resource.')
    }
  })
})

const loaded = $computed(() => engine.config.data != null)
</script>

<template>
  <c-app>
    <c-app-boundary>
      <div v-if="!loaded" class="flex h-screen w-screen items-center justify-center">
        <c-icon class="size-8 animate-spin text-primary" name="i-mdi-loading" />
      </div>
      <nuxt-layout v-else>
        <nuxt-page />
      </nuxt-layout>
    </c-app-boundary>
  </c-app>
</template>
