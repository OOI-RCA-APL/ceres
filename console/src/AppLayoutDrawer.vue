<script lang="ts" setup>
import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { Address } from '@/address'
import { postReload, useMutation } from '@/api/operations'
import { useAuth } from '@/auth'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { usePreferences } from '@/preferences'
import { useStore } from '@/store'
import { displayDuration } from '@/time'
import moment from 'moment'
import { LocalStorage, useQuasar } from 'quasar'
import { useRoute } from 'vue-router'

const auth = useAuth()
const store = useStore()
const drawer = useDrawer()
const quasar = useQuasar()
const route = useRoute()
const preferences = usePreferences()

function clearLocalStorage() {
  quasar
    .dialog({
      title: 'Clear Local Storage',
      class: 'no-shadow',
      message:
        'This will clear all saved UI state, form state and settings for this site from your ' +
        'local browser.',
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
        type: 'positive',
      })
    })
}

const root = new Address('@')

const reloadMutation = useMutation('reload', async () => {
  return await postReload()
})

function promptReload() {
  quasar
    .dialog({
      title: 'Confirm Reload',
      message: 'Are you sure you want to reload the engine configuration?',
      class: 'no-shadow',
      componentProps: {
        outline: true,
      },
      cancel: true,
      ok: {
        label: 'Reload',
        color: 'primary',
      },
    })
    .onOk(async () => {
      await executeReload()
    })
}

async function executeReload() {
  const result = await reloadMutation.mutateAsync()
  if (result.ok) {
    quasar.notify({
      message: 'Configuration reloaded successfully.',
      type: 'positive',
    })

    await store.load()
  } else {
    quasar.notify({
      message: 'Configuration reload failed.',
      type: 'negative',
      actions: [
        {
          label: 'Details',
          color: 'white',
          handler: () =>
            quasar.dialog({
              title: 'Error Details',
              message: `
<div class="full-width monospace-sm overflow-auto scroll" style="white-space: pre">
  ${JSON.stringify(result.error, null, 4)}
</div>
              `.trim(),
              html: true,
            }),
        },
      ],
    })
  }
}
</script>

<template>
  <q-drawer v-model="drawer.isOpen" :class="$style.root" side="left" :width="drawer.width">
    <div class="column full-height no-wrap overflow-hidden">
      <resize-handle
        v-model="drawer.width"
        :class="$style.resizeHandle"
        direction="horizontal"
        :max="600"
        :min="54"
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
          <app-layout-drawer-component
            v-if="store.componentRoot"
            :address="root"
            :component="store.componentRoot"
          />
        </q-list>
      </div>
      <q-separator />
      <q-list>
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.configuration" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Configuration</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.arrowRight" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
            <q-list bordered>
              <q-item clickable @click="promptReload">
                <q-item-section avatar>
                  <q-icon :name="icons.reload" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Reload</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-item>
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.preferences" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Preferences</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.arrowRight" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
            <q-card bordered flat :style="{ minWidth: '360px' }">
              <div class="items-center justify-evenly no-wrap row">
                <q-toggle
                  v-model="preferences.isDarkModeEnabled"
                  class="col q-pa-xs"
                  :icon="icons.darkMode"
                  label="Dark Mode"
                />
                <q-separator vertical />
                <q-toggle
                  v-model="preferences.isDeveloperModeEnabled"
                  class="col q-pa-xs"
                  :icon="icons.developer"
                  label="Developer Mode"
                />
              </div>
              <q-separator />
              <div class="q-pa-sm">
                <q-select
                  v-model="preferences.statisticsDuration"
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
              </div>
            </q-card>
          </q-menu>
        </q-item>
        <template v-if="preferences.isDeveloperModeEnabled">
          <q-separator />
          <q-item clickable>
            <q-item-section avatar>
              <q-icon :name="icons.developer" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Developer</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon :name="icons.arrowRight" />
            </q-item-section>
            <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
              <q-list bordered>
                <q-item clickable @click="clearLocalStorage">
                  <q-item-section avatar>
                    <q-icon :name="icons.clearLocalStorage" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Clear Local Storage</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item clickable to="/developer/schema-form-playground">
                  <q-item-section avatar>
                    <q-icon :name="icons.json" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Schema Form Playground</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-item>
        </template>
        <q-separator />
        <q-item :to="auth.user == null ? '/login' : undefined">
          <q-item-section avatar>
            <q-icon :name="icons.user" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ auth.user != null ? auth.user.username : 'Login' }}</q-item-label>
          </q-item-section>
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
