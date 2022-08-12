<template>
  <q-layout class="self-layout" container view="hHh Lpr lff">
    <q-header class="bg-primary self-header shadow-none">
      <q-toolbar class="no-wrap">
        <q-btn
          class="q-px-sm"
          flat
          :icon="icons.menu"
          @click="state.isDrawerOpen = !state.isDrawerOpen"
        />
        <q-toolbar-title @click="router.push('/')">
          <common-text variant="title1">{{ constants.appName }}</common-text>
        </q-toolbar-title>
        <q-btn
          class="q-px-sm"
          dense
          flat
          :icon="state.isDarkModeEnabled ? icons.darkMode : icons.lightMode"
          @click="state.isDarkModeEnabled = !state.isDarkModeEnabled"
        />
      </q-toolbar>
    </q-header>
    <q-drawer v-model="state.isDrawerOpen" bordered :breakpoint="1250" :width="160">
      <q-scroll-area class="fit">
        <q-list>
          <q-item clickable to="/units">
            <q-item-section avatar>
              <q-icon :name="icons.units" />
            </q-item-section>
            <q-item-section avatar>
              <q-item-label>Units</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>
    </q-drawer>
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
import { useQuasar } from 'quasar'
import { watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Zod from 'zod'
import AppBoundary from './AppBoundary.vue'
import CommonText from './components/CommonText.vue'
import PageSpinner from './components/PageSpinner.vue'
import constants from './constants'
import icons from './icons'
import { usePersisted } from './persistence'

const route = useRoute()
const router = useRouter()
const quasar = useQuasar()

const StateSchema = Zod.object({
  isDrawerOpen: Zod.boolean().default(true),
  isDarkModeEnabled: Zod.boolean().default(false),
})

const state = usePersisted({
  schema: StateSchema,
  methods: [{ type: 'local-storage', key: 'app-layout' }],
})

watchEffect(() => {
  quasar.dark.set(state.isDarkModeEnabled)
})
</script>

<style lang="scss" scoped>
// .self-header {
//   box-shadow: 0 0 5px $grey-6;
// }

.self-layout {
  height: 100vh;
}
</style>
