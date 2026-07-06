<script lang="ts" setup>
import { upperFirst } from 'lodash-es'
import { LocalStorage } from 'quasar'
import { useRoute } from 'vue-router'
import Zod from 'zod'

import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import AppLayoutDrawerWorkspace from '@/AppLayoutDrawerWorkspace.vue'
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
import { duration } from '@/time'
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
const isDevelopment = process.env.DEV

const persisted = usePersisted({
  schema: ({ object, boolean, number }) =>
    object({
      isShowingWorkspaces: boolean().default(false),
      workspaceDropdownHeight: number().default(200),
      workspaceFilter: Zod.enum(['all', 'joined', 'unjoined']).default('all'),
    }),
  methods: [{ type: 'local-storage', key: 'component/app-layout-drawer' }],
})

const displayedWorkspaces = $computed(() => {
  if (persisted.workspaceFilter === 'all') {
    return [...workspaces.joined, ...workspaces.unjoined]
  } else if (persisted.workspaceFilter === 'joined') {
    return workspaces.joined
  } else if (persisted.workspaceFilter === 'unjoined') {
    return workspaces.unjoined
  }
})

async function createWorkspace() {
  const created = await workspaces.create()
  workspaces.open(created.id)
}

async function importWorkspaces() {
  const imported = await workspaces.importFiles()
  if (imported != null && imported.length > 0) {
    workspaces.open(imported[0].id)
  }
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
      title: 'Reload Engine Configuration',
      message:
        'Apply any new changes in the configuration file (ceres.yaml) to the running engine?',
      class: 'no-shadow',
      componentProps: {
        outline: true,
      },
      ok: {
        label: 'Yes',
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
        :min="250"
        :style="{ left: `${drawer.width}px` }"
      />
      <div class="col-grow overflow-scroll scroll" style="height: 0">
        <q-list dense>
          <q-item :active="route.fullPath === '/'" :class="$style.largeItem" clickable to="/">
            <q-item-section avatar>
              <q-icon :name="icons.dashboard" />
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
                  />
                </q-btn>
              </div>
              <q-item-section no-wrap>
                <q-item-label class="q-ml-md">
                  Workspaces
                  <q-chip class="no-shadow q-ml-sm" clickable :icon="icons.filter" size="10px">
                    {{ upperFirst(persisted.workspaceFilter) }}
                    <q-menu anchor="top right" :offset="[8, 0]" self="top left">
                      <q-card bordered flat>
                        <q-list dense>
                          <q-item
                            v-close-popup
                            clickable
                            @click="persisted.workspaceFilter = 'all'"
                          >
                            <q-item-section>
                              <q-item-label>All</q-item-label>
                            </q-item-section>
                          </q-item>
                          <q-item
                            v-close-popup
                            clickable
                            @click="persisted.workspaceFilter = 'joined'"
                          >
                            <q-item-section>
                              <q-item-label>Joined</q-item-label>
                            </q-item-section>
                          </q-item>
                          <q-item
                            v-close-popup
                            clickable
                            @click="persisted.workspaceFilter = 'unjoined'"
                          >
                            <q-item-section>
                              <q-item-label>Unjoined</q-item-label>
                            </q-item-section>
                          </q-item>
                        </q-list>
                      </q-card>
                    </q-menu>
                  </q-chip>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="items-center row">
                  <q-btn flat :icon="icons.more" round size="xs">
                    <q-menu anchor="top right" :offset="[8, 5]" self="top left">
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
                          <q-item clickable @click="importWorkspaces">
                            <q-item-section avatar>
                              <q-icon :name="icons.import" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>Import</q-item-label>
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
              <q-list class="scroll" :style="{ height: `${persisted.workspaceDropdownHeight}px` }">
                <app-layout-drawer-workspace
                  v-for="workspace in displayedWorkspaces"
                  :key="workspace.id"
                  :workspace="workspace"
                />
              </q-list>
              <resize-handle
                v-model="persisted.workspaceDropdownHeight"
                :class="$style.workspaceDropdownResizeHandle"
                direction="vertical"
                :max="500"
                :min="36"
              />
            </div>
            <div class="scroll">
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
            <q-icon :name="icons.admin" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Admin</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" />
          </q-item-section>
          <q-menu anchor="top right" :offset="[8, 0]" self="top left">
            <q-card bordered>
              <q-list dense>
                <q-item to="/users">
                  <q-item-section avatar>
                    <q-icon :name="icons.user" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Users</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item to="/groups">
                  <q-item-section avatar>
                    <q-icon :name="icons.group" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Groups</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </q-menu>
        </q-item>
        <q-item v-if="engine.auth.isOperator" clickable>
          <q-item-section avatar>
            <q-icon :name="icons.configuration" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Configuration</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" />
          </q-item-section>
          <q-menu anchor="top right" :offset="[8, 0]" self="top left">
            <q-card bordered>
              <q-list dense>
                <q-item v-close-popup clickable @click="promptReload">
                  <q-item-section avatar>
                    <q-icon :name="icons.reload" />
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
            <q-icon :name="icons.preferences" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Preferences</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-icon :name="icons.menuRight" />
          </q-item-section>
          <q-menu anchor="bottom right" :offset="[8, 0]" self="bottom left">
            <q-card bordered flat :style="{ minWidth: '350px' }">
              <div class="items-center justify-evenly no-wrap row">
                <div class="col justify-center row">
                  <q-toggle
                    v-model="preferences.isDarkModeEnabled"
                    :icon="icons.darkMode"
                    label="Dark Mode"
                  />
                </div>
                <template v-if="isDevelopment">
                  <q-separator vertical />
                  <div class="col justify-center row">
                    <q-toggle
                      v-model="preferences.isDeveloperModeEnabled"
                      class="col"
                      :icon="icons.developer"
                      label="Developer Mode"
                    />
                  </div>
                </template>
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
                    duration(1, 'm'),
                    duration(5, 'm'),
                    duration(30, 'm'),
                    duration(1, 'h'),
                    duration(12, 'h'),
                    duration(1, 'd'),
                  ]"
                  options-dense
                  outlined
                />
              </div>
            </q-card>
          </q-menu>
        </q-item>
        <template v-if="isDevelopment && preferences.isDeveloperModeEnabled">
          <q-separator />
          <q-item clickable>
            <q-item-section avatar>
              <q-icon :name="icons.developer" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Developer</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-icon :name="icons.menuRight" />
            </q-item-section>
            <q-menu anchor="bottom right" :offset="[8, 0]" self="bottom left">
              <q-list bordered dense>
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
        <q-item :to="engine.auth.user == null ? '/login' : '/account'">
          <q-item-section avatar>
            <q-icon :name="icons.user" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ engine.auth.user != null ? engine.auth.user.username : 'Login' }}
            </q-item-label>
          </q-item-section>
          <q-item-section v-if="engine.auth.user" side>
            <q-chip
              class="q-px-sm"
              color="primary"
              dense
              :icon="icons[engine.auth.user.role]"
              size="10px"
              text-color="white"
            >
              {{ upperFirst(engine.auth.user.role) }}
              <q-tooltip class="bg-primary" :offset="[0, 8]">
                You are currently logged in with {{ engine.auth.user.role }}-level permissions.
              </q-tooltip>
            </q-chip>
          </q-item-section>
        </q-item>
      </q-list>
    </div>
  </q-drawer>
</template>

<style lang="scss" module>
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
