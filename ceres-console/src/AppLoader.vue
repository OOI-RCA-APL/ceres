<script lang="ts" setup>
import { useConfig } from '@/api/operations'
import { useSettings } from '@/settings'
import { useIntervalFn } from '@vueuse/core'
import { computed, provide, watchEffect } from 'vue'
import { THEME_KEY } from 'vue-echarts'

const settings = useSettings()

watchEffect(() => {
  const html = document.querySelector('html')
  if (html != null) {
    if (settings.isDarkModeEnabled) {
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
  computed(() => (settings.isDarkModeEnabled ? 'dark' : undefined))
)

const config = useConfig()

useIntervalFn(
  async () => {
    try {
      await config.load()
    } catch (error) {
      console.error(error)
    }

    if (config.data == null) {
      try {
        await config.refetch()
      } catch (error) {
        console.error(error)
      }
    }
  },
  1000,
  { immediate: true }
)
</script>

<template>
  <transition-group
    appear
    enter-active-class="animated fadeIn"
    leave-active-class="animated fadeOut"
  >
    <div
      v-if="config.data == null"
      key="loading"
      class="fixed-top-left items-center justify-center row window-height window-width"
    >
      <q-spinner-orbit color="primary" size="32px" />
    </div>
    <router-view v-else key="app" />
  </transition-group>
</template>
