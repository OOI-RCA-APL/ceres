<template>
  <router-view />
</template>

<script lang="ts" setup>
import { useQuasar } from 'quasar'
import { computed, provide } from 'vue'
import { THEME_KEY } from 'vue-echarts'

const quasar = useQuasar()

provide(
  THEME_KEY,
  computed(() => (quasar.dark.isActive ? 'dark' : undefined))
)
</script>
