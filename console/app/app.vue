<script lang="ts" setup>
import { useEventListener } from '@vueuse/core'
import { computed, watchEffect } from 'vue'

import { refreshDelayMs } from '@/api/auth'
import { useEngine } from '@/api/engine'
import constants from '@/constants'
import { useNavigation } from '@/navigation'
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

    void navigation.enforceAccess(engine.auth.user)
  })
})

const loaded = $computed(() => engine.config.data != null)
</script>

<template>
  <c-app>
    <c-app-boundary>
      <nuxt-layout>
        <nuxt-page />
      </nuxt-layout>
      <!-- Over the app rather than instead of it. Swapping the page out for a spinner leaves
      the router with nothing mounted to hand a route to, which Nuxt reports as `NuxtPage`
      going unused. -->
      <div v-if="!loaded" class="bg-default fixed inset-0 z-50 flex items-center justify-center">
        <c-icon class="size-8 animate-spin text-primary" name="i-mdi-loading" />
      </div>
    </c-app-boundary>
  </c-app>
</template>
