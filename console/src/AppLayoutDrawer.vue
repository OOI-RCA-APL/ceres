<script lang="ts" setup>
import moment from 'moment'
import { LocalStorage } from 'quasar'
import { useRoute } from 'vue-router'

import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useEngine } from '@/api/engine'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDialogs } from '@/dialogs'
import { useDrawer } from '@/drawer'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { usePersisted } from '@/persistence'
import { usePreferences } from '@/preferences'
import { displayDuration } from '@/utilities'
import { useWorkspaces } from '@/workspace'

const auth = useAuth()
const engine = useEngine()
const drawer = useDrawer()
const notify = useNotify()
const dialogs = useDialogs()
const workspaces = useWorkspaces()
const route = useRoute()
const preferences = usePreferences()

const iconSize = '18px'

const persisted = usePersisted({
  schema: ({ object, boolean, number }) =>
    object({
      isShowingWorkspaces: boolean().default(false),
      workspaceDropdownHeight: number().default(200),
    }),
  methods: [{ type: 'local-storage', key: 'component/app-layout-drawer' }],
})

async function createWorkspace() {
  const created = await workspaces.create()
  workspaces.open(created.id)
}

function clearLocalStorage() {
  dialogs
    .show({
      title: 'Clear Local Storage',
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
      notify.success('Local storage cleared successfully.', {
        icon: icons.clearLocalStorage,
      })
    })
}

const root = new Address('@')

function promptReload() {
  dialogs
    .show({
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
      await guard(engine.reload(), (error) => {
        notify.error('Configuration reload failed.', {
          actions: [
            {
              label: 'Details',
              color: 'white',
              handler: () =>
                dialogs.show({
                  title: 'Error Details',
                  message: JSON.stringify(error, null, 4).trim(),
                  html: true,
                }),
            },
          ],
        })
      })

      notify.success('Configuration reloaded successfully.')
      await engine.auth.refresh()
    })
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
      <div class="col-grow overflow-scroll scroll" style="height: 0">
        <q-list dense>
          <q-item :active="route.fullPath === '/'" :class="$style.largeItem" clickable to="/">
            <q-item-section avatar>
              <q-icon :name="icons.dashboard" :size="iconSize" />
            </q-item-section>
            <q-item-section avatar>
              <q-item-label>Dashboard</q-item-label>
            </q-item-section>
          </q-item>
          <template v-if="auth.isViewer">
            <q-item :active="route.fullPath.startsWith('/workspaces')" class="items-center row">
              <div :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']">
                <q-btn
                  :class="$style.toggleButton"
                  flat
                  round
                  size="xs"
                  tabindex="0"
                  @click.stop.prevent="
                    persisted.isShowingWorkspaces = !persisted.isShowingWorkspaces
                  "
                >
                  <q-icon
                    :name="persisted.isShowingWorkspaces ? icons.menuDown : icons.menuRight"
                    :size="iconSize"
                  />
                </q-btn>
              </div>
              <q-item-section no-wrap>
                <q-item-label class="q-ml-md">Workspaces</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="items-center row">
                  <q-btn flat :icon="icons.more" round size="xs">
                    <q-menu class="no-shadow">
                      <q-card bordered>
                        <q-list dense>
                          <q-item clickable @click="createWorkspace">
                            <q-item-section avatar>
                              <q-icon :name="icons.add" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>New</q-item-label>
                            </q-item-section>
                          </q-item>
                        </q-list>
                      </q-card>
                    </q-menu>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
            <div v-if="persisted.isShowingWorkspaces" class="relative-position">
              <q-list
                class="overflow-hidden scroll"
                :style="{ height: `${persisted.workspaceDropdownHeight}px` }"
              >
                <q-item
                  v-for="workspace in workspaces.joined"
                  :key="workspace.id"
                  clickable
                  dense
                  :to="`/workspaces/${workspace.id}`"
                >
                  <q-item-section avatar>
                    <q-icon class="q-ml-md" :name="icons.circle" size="7px" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>
                      <span class="q-ml-sm" style="text-wrap: nowrap">
                        {{ workspace.name }}
                      </span>
                    </q-item-label>
                  </q-item-section>
                </q-item>
                <template v-if="workspaces.unjoined.length > 0">
                  <q-separator />
                  <q-item
                    v-for="workspace in workspaces.unjoined"
                    :key="workspace.id"
                    clickable
                    dense
                    :to="`/workspaces/${workspace.id}`"
                  >
                    <q-item-section avatar>
                      <q-icon class="q-ml-md" :name="icons.circle" size="7px" />
                    </q-item-section>
                    <q-item-section no-wrap>
                      <q-item-label>
                        <span class="q-ml-sm" style="text-wrap: nowrap">
                          {{ workspace.name }}
                        </span>
                      </q-item-label>
                    </q-item-section>
                    <q-item-section side>
                      <q-btn color="primary" label="Join" round />
                    </q-item-section>
                  </q-item>
                </template>
                <resize-handle
                  v-model="persisted.workspaceDropdownHeight"
                  :class="$style.workspaceDropdownResizeHandle"
                  direction="vertical"
                  :max="400"
                  :min="34"
                />
              </q-list>
            </div>
            <div class="overflow-hidden scroll">
              <app-layout-drawer-component
                v-if="engine.components.root != null"
                :address="root"
                :component="engine.components.root"
              />
            </div>
          </template>
        </q-list>
      </div>
      <q-separator />
      <q-list dense>
        <q-item v-if="engine.auth.isAdmin" clickable>
          <q-item-section avatar>
            <q-icon :name="icons.admin" :size="iconSize" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Admin</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" :size="iconSize" />
          </q-item-section>
          <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
            <q-card bordered>
              <q-list dense>
                <q-item to="/users">
                  <q-item-section avatar>
                    <q-icon :name="icons.user" :size="iconSize" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Users</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </q-menu>
        </q-item>
        <q-item v-if="engine.auth.isOperator" clickable>
          <q-item-section avatar>
            <q-icon :name="icons.configuration" :size="iconSize" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Configuration</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" :size="iconSize" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
            <q-card bordered>
              <q-list dense>
                <q-item clickable @click="promptReload">
                  <q-item-section avatar>
                    <q-icon :name="icons.reload" :size="iconSize" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Reload Engine Configuration</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </q-menu>
        </q-item>
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.preferences" :size="iconSize" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Preferences</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" :size="iconSize" />
          </q-item-section>
          <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
            <q-card bordered flat :style="{ minWidth: '350px' }">
              <div class="items-center justify-evenly no-wrap row">
                <q-toggle
                  v-model="preferences.isDarkModeEnabled"
                  class="col"
                  :icon="icons.darkMode"
                  label="Dark Mode"
                />
                <q-separator vertical />
                <q-toggle
                  v-model="preferences.isDeveloperModeEnabled"
                  class="col"
                  :icon="icons.developer"
                  label="Developer Mode"
                />
              </div>
              <q-separator />
              <div class="q-pb-xs q-pt-sm q-px-sm">
                <q-select
                  v-model="preferences.statisticsDuration"
                  dense
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
                  outlined
                />
              </div>
            </q-card>
          </q-menu>
        </q-item>
        <template v-if="preferences.isDeveloperModeEnabled">
          <q-separator />
          <q-item clickable>
            <q-item-section avatar>
              <q-icon :name="icons.developer" :size="iconSize" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Developer</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon :name="icons.menuRight" />
            </q-item-section>
            <q-menu anchor="bottom right" class="no-shadow" :offset="[8, 0]" self="bottom left">
              <q-list bordered dense>
                <q-item clickable @click="clearLocalStorage">
                  <q-item-section avatar>
                    <q-icon :name="icons.clearLocalStorage" :size="iconSize" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Clear Local Storage</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item clickable to="/developer/schema-form-playground">
                  <q-item-section avatar>
                    <q-icon :name="icons.json" :size="iconSize" />
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
        <q-item :to="engine.auth.user == null ? '/login' : '/account'">
          <q-item-section avatar>
            <q-icon :name="icons.user" :size="iconSize" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{
              engine.auth.user != null ? engine.auth.user.username : 'Login'
            }}</q-item-label>
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

.toggleButton {
  margin-left: -22px;
}

.iconContainer {
  min-width: 40px;
}

.workspaceDropdownResizeHandle {
  position: absolute;
  bottom: 0;
  left: 0;
}

.largeItem {
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}
</style>
