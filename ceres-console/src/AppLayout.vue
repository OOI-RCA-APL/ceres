<template>
  <q-layout class="self-layout" container view="hHh Lpr lff">
    <q-header class="bg-primary shadow-none">
      <q-toolbar class="no-wrap">
        <q-btn
          class="q-px-sm"
          flat
          :icon="icons.menu"
          @click="state.isDrawerOpen = !state.isDrawerOpen"
        />
        <q-toolbar-title class="cursor-pointer" @click="router.push('/')">
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
    <q-drawer v-model="state.isDrawerOpen" bordered :width="200">
      <q-scroll-area class="fit">
        <q-list>
          <q-item :active="route.fullPath === '/'" clickable to="/">
            <q-item-section avatar>
              <q-icon :name="icons.dashboard" />
            </q-item-section>
            <q-item-section avatar>
              <q-item-label>Dashboard</q-item-label>
            </q-item-section>
          </q-item>
          <q-expansion-item
            v-model="state.isUnitsSectionExpanded"
            :icon="icons.units"
            label="Units"
          >
            <q-item
              v-for="unit in config.data.units"
              :key="unit.name"
              clickable
              dense
              style="min-height: 38px"
              :to="`/units/${unit.name}`"
            >
              <q-item-section avatar>
                <q-icon :name="icons.unit" size="12px" style="margin-left: 6px" />
              </q-item-section>
              <q-item-section>
                <q-item-label class="text-no-wrap">@{{ unit.name }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-expansion-item>
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

import { useConfig } from '@/api/queries'
const route = useRoute()
const router = useRouter()
const quasar = useQuasar()

const StateSchema = Zod.object({
  isDrawerOpen: Zod.boolean().default(false),
  isDarkModeEnabled: Zod.boolean().default(false),
  isUnitsSectionExpanded: Zod.boolean().default(true),
})

const state = usePersisted({
  schema: StateSchema,
  methods: [{ type: 'local-storage', key: 'app-layout' }],
})

watchEffect(() => {
  quasar.dark.set(state.isDarkModeEnabled)
})
const config = useConfig()
</script>

<style lang="scss" scoped>
.self-layout {
  height: 100vh;
}
</style>
