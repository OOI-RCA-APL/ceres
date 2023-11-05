<script lang="ts" setup>
import constants from '@/constants'
import { usePreferences } from '@/preferences'
import { useStore } from '@/store'
import { useIntervalFn } from '@vueuse/core'
import { useMeta } from 'quasar'
import { computed, provide, watchEffect } from 'vue'
import { THEME_KEY } from 'vue-echarts'

const preferences = usePreferences()

watchEffect(() => {
  const html = document.querySelector('html')
  if (html != null) {
    if (preferences.isDarkModeEnabled) {
      html.classList.add('dark')
      html.classList.remove('light')
    } else {
      html.classList.add('light')
      html.classList.remove('dark')
    }
  }
})

provide(
  THEME_KEY,
  computed(() => (preferences.isDarkModeEnabled ? 'dark' : undefined))
)

const store = useStore()

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
  title: store.config?.server?.console?.title ?? constants.defaultTitle,
}))
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
@/preferences
