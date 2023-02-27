<template>
  <q-layout class="self-app-layout-root" container view="hHh Lpr lff">
    <app-layout-header />
    <app-layout-drawer />
    <q-page-container :key="route.path">
      <app-boundary>
        <suspense>
          <template #default>
            <router-view />
          </template>
          <template #fallback>
            <page-spinner />
          </template>
        </suspense>
      </app-boundary>
    </q-page-container>
  </q-layout>
</template>

<script lang="ts" setup>
import AppBoundary from '@/AppBoundary.vue'
import AppLayoutDrawer from '@/AppLayoutDrawer.vue'
import AppLayoutHeader from '@/AppLayoutHeader.vue'
import PageSpinner from '@/components/PageSpinner.vue'
import { useQuasar } from 'quasar'
import { onErrorCaptured } from 'vue'
import { useRoute } from 'vue-router'

const quasar = useQuasar()
const route = useRoute()

onErrorCaptured((error) => {
  console.error(error)
  quasar.notify({
    message: 'An unexpected error occurred. You may need to refresh the page.',
    color: 'negative',
    group: 'unexpected',
    position: 'bottom',
    timeout: 10000,
    badgeStyle: {
      display: 'none',
    },
  })

  return true
})
</script>

<style lang="scss" scoped>
.self-app-layout-root {
  height: 100vh;
}
</style>
