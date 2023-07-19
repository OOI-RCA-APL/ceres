<script lang="ts" setup>
import { useConfig } from '@/api/operations'
import { useQuasar } from 'quasar'
import { computed, provide, watchEffect } from 'vue'
import { THEME_KEY } from 'vue-echarts'

const quasar = useQuasar()
provide(
  THEME_KEY,
  computed(() => (quasar.dark.isActive ? 'dark' : undefined))
)

const config = useConfig()
await config.load()

watchEffect(() => {
  const html = document.querySelector('html')
  if (html != null) {
    if (quasar.dark.isActive) {
      html.classList.add('dark')
      html.classList.remove('light')
    } else {
      html.classList.add('light')
      html.classList.remove('dark')
    }
  }
})
</script>

<template>
  <router-view />
</template>
