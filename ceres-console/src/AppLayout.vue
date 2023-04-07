<script lang="ts" setup>
import AppBoundary from '@/AppBoundary.vue'
import AppLayoutDrawer from '@/AppLayoutDrawer.vue'
import AppLayoutHeader from '@/AppLayoutHeader.vue'
import PageSpinner from '@/components/PageSpinner.vue'
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <q-layout :class="$style.root" container view="hHh Lpr lff">
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

<style module>
.root {
  height: 100vh;
}
</style>
