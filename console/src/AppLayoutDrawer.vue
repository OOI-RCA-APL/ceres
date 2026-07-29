<script lang="ts" setup>
import { LocalStorage } from 'quasar'
import { useRoute } from 'vue-router'

import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import AppLayoutDrawerHeader from '@/AppLayoutDrawerHeader.vue'
import { useAccess } from '@/api/access'
import { useAuth } from '@/api/auth'
import { useEngine } from '@/api/engine'
import ResizeHandle from '@/components/ResizeHandle.vue'
import UserChooser from '@/components/UserChooser.vue'
import { useDialogs } from '@/dialogs'
import { useDrawer } from '@/drawer'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { duration } from '@/time'
import { displayDuration } from '@/utilities'
import { useWorkspaces } from '@/workspace'

const access = useAccess()
const auth = useAuth()
const engine = useEngine()
const drawer = useDrawer()
const navigation = useNavigation()
const notify = useNotify()
const dialogs = useDialogs()
const workspaces = useWorkspaces()
const route = useRoute()
const preferences = usePreferences()
const isDevelopment = process.env.DEV

// Narrows the tree to what answers it, keeping the path down to each match. Held here rather than
// persisted, since a filter is a question being asked now and not a preference.
let componentFilter = $ref('')

// What the header reports. Components that answer the filter rather than rows left showing, since
// a parent kept only to carry a matching child is a path to an answer and not one itself.
// Which top level component the open one is in, or below. The tree's own rows work this out for
// their children, and this is the same answer for the header, which the tree hangs from.
const activeTopLevelIndex = $computed(() => {
  const active = typeof route.params.address === 'string' ? route.params.address : null
  if (active == null) {
    return -1
  }

  return engine.components.topLevel.findIndex((component) => {
    const own = component.address.toString()
    return active === own || active.startsWith(`${own}.`)
  })
})

const matchingComponents = $computed(() => {
  const text = componentFilter.trim().toLowerCase()
  if (text === '') {
    return engine.components.all.length
  }

  return engine.components.all.filter((component) =>
    component.address.toString().toLowerCase().includes(text)
  ).length
})

const isDeveloperMode = $computed(() => isDevelopment && preferences.isDeveloperModeEnabled)

// The engine decides whether impersonation exists at all, and only an administrator may do it.
const canImpersonate = $computed(() => engine.auth.canImpersonate && engine.auth.isAdmin)

void engine.auth.loadFeatures()

// Everything the console shows is filtered by who the caller is, so the access map, the workspace
// list and the current page all have to be rebuilt around the new identity.
async function adoptIdentity(change: Promise<unknown>) {
  await guard(change, () => notify.error('Failed to change user.'))
  await access.refresh()
  await workspaces.refresh()
  navigation.reload()
}

async function impersonate(userId: string) {
  await adoptIdentity(engine.auth.impersonate(userId))
}

async function stopImpersonating() {
  await adoptIdentity(engine.auth.stopImpersonating())
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
          <q-item :active="route.path === '/'" :class="$style.largeItem" clickable to="/">
            <q-item-section avatar>
              <q-icon :name="icons.home" />
            </q-item-section>
            <q-item-section avatar>
              <q-item-label>Home</q-item-label>
            </q-item-section>
          </q-item>
          <div v-if="auth.isViewer" class="scroll">
            <template v-if="engine.components.topLevel.length > 0">
              <app-layout-drawer-header
                v-model:filter="componentFilter"
                :count="matchingComponents"
                :on-path="activeTopLevelIndex >= 0"
              />
            </template>
            <app-layout-drawer-component
              v-for="(component, index) in engine.components.topLevel"
              :key="component.address.toString()"
              :active-after-me="activeTopLevelIndex > index"
              :address="component.address"
              :component="component"
              :filter="componentFilter"
              :has-following-sibling="index < engine.components.topLevel.length - 1"
            />
          </div>
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
                <!-- Taking on another identity is something an administrator does, so it sits with
                the rest of what only they can reach rather than behind a switch about whether
                development tools are wanted. The engine decides whether it exists at all. -->
                <template v-if="canImpersonate">
                  <q-separator />
                  <q-item clickable>
                    <q-item-section avatar>
                      <q-icon :name="icons.viewer" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Impersonate</q-item-label>
                      <q-item-label caption>Intended for development.</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                      <q-icon :name="icons.menuRight" />
                    </q-item-section>
                    <q-menu anchor="top right" :offset="[8, 0]" self="top left">
                      <q-card bordered flat :style="{ width: '300px' }">
                        <user-chooser
                          empty="No other users to impersonate."
                          :omit="(user) => user.id === engine.auth.user?.id"
                          @select="(user) => impersonate(user.id)"
                        />
                      </q-card>
                    </q-menu>
                  </q-item>
                </template>
              </q-list>
            </q-card>
          </q-menu>
        </q-item>
        <q-item v-if="engine.auth.isAdmin" clickable>
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
        <!-- Everything here is a development tool, impersonation included, which the engine warns
        should only be turned on while developing. So the whole section follows the one switch that
        says whether these are wanted, rather than a menu that stays put while emptying out. -->
        <template v-if="isDeveloperMode">
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
                <q-item v-if="isDeveloperMode" clickable @click="clearLocalStorage">
                  <q-item-section avatar>
                    <q-icon :name="icons.clearLocalStorage" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Clear Local Storage</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-if="isDeveloperMode" clickable to="/developer/schema-form-playground">
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
        <!-- Impersonating is a state the whole console is in, so getting back out of it stays
        at the top level rather than inside the menu that started it. -->

        <template v-if="engine.auth.isImpersonating">
          <q-separator />
          <q-item clickable @click="stopImpersonating">
            <q-item-section avatar>
              <q-icon color="warning" :name="icons.viewer" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Impersonating {{ engine.auth.user?.username }}</q-item-label>
              <q-item-label caption>Return to your own account.</q-item-label>
            </q-item-section>
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
          <q-item-section v-if="engine.auth.user?.admin" side>
            <q-chip
              class="q-px-sm"
              color="primary"
              dense
              :icon="icons.admin"
              size="10px"
              text-color="white"
            >
              Admin
              <q-tooltip class="bg-primary" :offset="[0, 8]">
                You are logged in with administrative access.
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

// Quasar reserves 56px for an icon, which is generous for a sidebar whose rows are one glyph and
// one word, and which spends that width again on every level of the component tree. Narrowed once
// here rather than per row, so every label in the drawer still starts on the same rail. Menus are
// teleported out of the drawer, so their own rows keep the default.
.root :global(.q-item__section--avatar) {
  min-width: 36px;
  padding-right: 0;
}

.resizeHandle {
  position: absolute;
  top: 0;
}

// Quiet until it is being used, so an empty filter reads as part of the tree rather than as a
// control demanding to be filled in.
.filter {
  opacity: 0.55;
  transition: opacity 0.15s;

  &:hover,
  &:focus-within {
    opacity: 1;
  }
}

// Inherits the row it sits in, so the text a filter is typed into looks like the names it is
// matching against rather than like a form field dropped among them.
.filterInput {
  width: 100%;
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  outline: none;

  &::placeholder {
    color: inherit;
    opacity: 0.7;
  }
}

.largeItem {
  padding-top: 12px !important;
  padding-bottom: 12px !important;
}
</style>
