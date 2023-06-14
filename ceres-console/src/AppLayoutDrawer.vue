<script lang="ts" setup>
import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { Address } from '@/address'
import { useConfig } from '@/api/operations'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useSettings } from '@/settings'
import { displayDuration } from '@/time'
import moment from 'moment'
import { LocalStorage, useQuasar } from 'quasar'
import { useRoute } from 'vue-router'

const config = useConfig()
const drawer = useDrawer()
const quasar = useQuasar()
const route = useRoute()
const settings = useSettings()

function clearLocalStorage() {
  quasar
    .dialog({
      title: 'Clear Local Storage',
      class: 'no-shadow',
      message:
        'This action will clear all saved UI state, form state and settings for this site from ' +
        'your local browser. This can be useful if you have managed to get the application ' +
        'into an undesirable state and want to get back to a clean slate.',
      ok: {
        label: 'Clear',
        color: 'primary',
        flat: true,
      },
      cancel: {
        label: 'Cancel',
        flat: true,
        color: 'grey',
      },
    })
    .onOk(() => {
      LocalStorage.clear()
      quasar.notify({
        message: 'Local storage cleared successfully.',
        icon: icons.clearLocalStorage,
        color: 'positive',
      })
    })
}

const root = new Address('')
</script>

<template>
  <q-drawer v-model="drawer.isOpen" :class="$style.root" :width="drawer.width">
    <div class="column full-height">
      <resize-handle
        v-model="drawer.width"
        :class="$style.resizeHandle"
        direction="horizontal"
        :min="60"
        :style="{ left: `${drawer.width}px` }"
      />
      <div class="col-grow scroll">
        <q-list>
          <q-item :active="route.fullPath === '/'" clickable to="/">
            <q-item-section avatar>
              <q-icon :name="icons.dashboard" />
            </q-item-section>
            <q-item-section avatar>
              <q-item-label>Dashboard</q-item-label>
            </q-item-section>
          </q-item>
          <app-layout-drawer-component :address="root" :config="config.data" />
        </q-list>
      </div>
      <q-list>
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.tools" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Tools</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.arrowRight" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
            <q-list bordered>
              <q-item clickable to="/tools/schema-form-playground">
                <q-item-section avatar>
                  <q-icon :name="icons.json" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Schema Form Playground</q-item-label>
                </q-item-section>
              </q-item>
              <q-item clickable @click="clearLocalStorage">
                <q-item-section avatar>
                  <q-icon :name="icons.clearLocalStorage" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Clear Local Storage</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-item>
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.settings" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Settings</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.arrowRight" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, -8]" self="bottom left">
            <q-card bordered class="q-pa-sm" flat :style="{ minWidth: '350px' }">
              <q-toggle
                v-model="settings.isDarkModeEnabled"
                :icon="icons.darkMode"
                label="Dark Mode"
              />
              <q-separator class="q-my-sm" />
              <q-select
                v-model="settings.statisticsDuration"
                dense
                filled
                hint="The time over which statistics, like alert counts, are calculated."
                label="Statistics Duration"
                :option-label="displayDuration"
                :options="[
                  moment.duration(1, 'm'),
                  moment.duration(5, 'm'),
                  moment.duration(30, 'm'),
                  moment.duration(1, 'h'),
                  moment.duration(12, 'h'),
                  moment.duration(1, 'd'),
                ]"
                options-dense
              />
            </q-card>
          </q-menu>
        </q-item>
      </q-list>
    </div>
  </q-drawer>
</template>

<style module>
.root {
  overflow: visible !important;
  position: relative;
}

.resizeHandle {
  position: absolute;
  top: 0;
}
</style>
