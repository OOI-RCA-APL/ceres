<script lang="ts" setup>
import constants from '@/constants'
import { useNavigation } from '@/navigation'
import { usePreferences } from '@/preferences'
import { userCanAccess } from '@/router'
import { useStore } from '@/store'
import { useEventListener, useIntervalFn } from '@vueuse/core'
import moment from 'moment'
import { useMeta, useQuasar } from 'quasar'
import { computed, onMounted, provide, watchEffect } from 'vue'
import { THEME_KEY } from 'vue-echarts'

const navigation = useNavigation()
const store = useStore()
const preferences = usePreferences()
const quasar = useQuasar()

watchEffect(() => {
  const html = document.querySelector('html')
  if (preferences.isDarkModeEnabled) {
    if (html != null) {
      html.classList.add('dark')
      html.classList.remove('light')
    }
  } else {
    if (html != null) {
      html.classList.add('light')
      html.classList.remove('dark')
    }
  }
})

provide(
  THEME_KEY,
  computed(() => (preferences.isDarkModeEnabled ? 'dark' : undefined))
)

useIntervalFn(async () => {
  if (store.isLoadingConfig) {
    return
  }

  if (store.config == null) {
    try {
      await store.refetchConfig()
    } catch (error) {
      console.error(error)
    }
  }
}, 1000)

useMeta(() => ({
  title: store.config?.title ?? constants.defaultTitle,
}))

function notifyAccessBlocked() {
  quasar.notify({
    message: 'You do not have access to that resource.',
    color: 'warning',
  })
}

function notifyLoggedOut() {
  quasar.notify({
    message: 'You have been signed out due to inactivity.',
    color: 'warning',
  })
}

function getLoginRedirectPath(redirect?: string) {
  return `/login?redirect=${encodeURI(redirect ?? navigation.route.fullPath)}`
}

async function refresh() {
  console.log('Refreshing authentication...')
  const user = await store.refresh()
  if (user != null) {
    console.log('Authentication refreshed successfully.')
  } else {
    console.log('Authentication refresh failed.')
  }
}

// If we are logged in, set a timeout to do a refresh just before the access token expires.
watchEffect((onInvalidate) => {
  if (store.identity?.expires == null) {
    return
  }

  const ms = moment
    .duration(moment.utc(store.identity.expires).subtract(1, 'minute').diff(moment()))
    .asMilliseconds()

  const timeout = setTimeout(() => {
    void refresh()
  }, Math.max(ms, 0))

  onInvalidate(() => {
    clearTimeout(timeout)
  })
})

onMounted(() => {
  const remove = navigation.router.beforeEach((to, _from, next) => {
    if (userCanAccess(store.user, to)) {
      next()
    } else {
      next(getLoginRedirectPath(to.fullPath))
      notifyAccessBlocked()
    }
  })

  return () => {
    remove()
  }
})

useEventListener(window, 'focus', () => {
  const wasLoggedIn = store.user != null
  void refresh().then(() => {
    if (wasLoggedIn && store.user == null) {
      notifyLoggedOut()
    }

    if (!userCanAccess(store.user, navigation.route)) {
      void navigation.replace(getLoginRedirectPath())
      notifyAccessBlocked()
    }
  })
})

await refresh()

// Here we're getting the initial route directly from the resolve function because at this point in
// the loading process we haven't actually navigated to the initial route yet. As such, we can't use
// the "current" route object from "useRoute()".
const initialRoute = navigation.resolve(window.location.pathname)
if (initialRoute != null && !userCanAccess(store.user, initialRoute)) {
  await navigation.replace(getLoginRedirectPath())
  notifyAccessBlocked()
}
</script>

<template>
  <transition-group
    appear
    enter-active-class="animated fadeIn"
    leave-active-class="animated fadeOut"
  >
    <div
      v-if="store.config == null"
      key="loading"
      class="fixed-top-left items-center justify-center row window-height window-width"
    >
      <q-spinner-orbit color="primary" size="32px" />
    </div>
    <router-view v-else key="app" />
  </transition-group>
</template>
