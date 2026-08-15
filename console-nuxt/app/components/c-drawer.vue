<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { useRoute } from 'vue-router'

import { useEngine } from '@/api/engine'
import { useDialogs } from '@/dialogs'
import { useDrawer } from '@/drawer'
import { guard } from '@/errors'
import icons from '@/icons'
import { routeComponentAddress, useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { usePreferences } from '@/preferences'
import { displayDuration, duration } from '@/time'

const engine = useEngine()
const drawer = useDrawer()
const navigation = useNavigation()
const notify = useNotify()
const dialogs = useDialogs()
const preferences = usePreferences()
const route = useRoute()
const isDevelopment = import.meta.dev

// Narrows the tree to what answers it, keeping the path down to each match. Held here rather than
// persisted, since a filter is a question being asked now and not a preference.
let componentFilter = $ref('')

// Which top level component the open one is in, or below. The tree's own rows work this out for
// their children, and this is the same answer for the header, which the tree hangs from.
const activeTopLevelIndex = $computed(() => {
  const active = routeComponentAddress(route)
  if (active == null) {
    return -1
  }

  return engine.components.topLevel.findIndex((component) => {
    const own = component.address.toString()
    return active === own || active.startsWith(`${own}.`)
  })
})

// What the header reports. Components that answer the filter rather than rows left showing, since
// a parent kept only to carry a matching child is a path to an answer and not one itself.
const matchingComponents = $computed(() => {
  const text = componentFilter.trim().toLowerCase()
  if (text === '') {
    return engine.components.all.length
  }

  return engine.components.all.filter((component) =>
    component.address.toString().toLowerCase().includes(text),
  ).length
})

const isDeveloperMode = $computed(() => isDevelopment && preferences.isDeveloperModeEnabled)

void engine.auth.loadFeatures()

const statisticsDurations = [
  duration(1, 'm'),
  duration(5, 'm'),
  duration(30, 'm'),
  duration(1, 'h'),
  duration(12, 'h'),
  duration(1, 'd'),
]

const adminItems: DropdownMenuItem[][] = [
  [
    { label: 'Users', icon: icons.user, to: '/users' },
    { label: 'Groups', icon: icons.group, to: '/groups' },
  ],
]

const developerItems = $computed<DropdownMenuItem[][]>(() => [
  [
    {
      label: 'Clear Local Storage',
      icon: icons.clearLocalStorage,
      onSelect: clearLocalStorage,
    },
    {
      label: 'Schema Form Playground',
      icon: icons.json,
      to: '/developer/schema-form-playground',
    },
  ],
])

function clearLocalStorage() {
  dialogs
    .show({
      title: 'Clear Local Storage',
      message:
        'This will clear all saved UI state, form state and settings for this site from your ' +
        'local browser.',
      okLabel: 'Clear',
    })
    .onOk(() => {
      window.localStorage.clear()
      notify.success('Local storage cleared successfully.', { icon: icons.clearLocalStorage })
    })
}

function promptReload() {
  dialogs
    .show({
      title: 'Reload Engine Configuration',
      message:
        'Apply any new changes in the configuration file (ceres.yaml) to the running engine?',
      okLabel: 'Yes',
    })
    .onOk(async () => {
      await guard(engine.reload(), () => {
        notify.error('Configuration reload failed.')
      })

      notify.success('Configuration reloaded successfully.')
      await engine.auth.refresh()
    })
}

// Everything the console shows is filtered by who the caller is, so the access map, the workspace
// list and the current page all have to be rebuilt around the new identity.
async function stopImpersonating() {
  await guard(engine.auth.stopImpersonating(), () => notify.error('Failed to change user.'))
  await engine.access.refresh()
  await engine.workspaces.refresh()
  navigation.reload()
}

const footerRowClass =
  'hover:bg-elevated flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-sm'
</script>

<template>
  <aside class="bg-default border-default flex flex-col overflow-hidden border-r">
    <c-resize-handle
      v-model="drawer.width"
      class="absolute top-0 z-10"
      direction="horizontal"
      :max="600"
      :min="250"
      :style="{ left: `${drawer.width}px` }"
    />
    <div class="grow overflow-y-auto">
      <nuxt-link :class="[footerRowClass, 'py-3']" to="/">
        <c-icon class="size-5" :name="icons.home" />
        <span>Home</span>
      </nuxt-link>
      <template v-if="engine.auth.isViewer && engine.components.topLevel.length > 0">
        <c-drawer-components-header
          v-model:filter="componentFilter"
          :count="matchingComponents"
          :on-path="activeTopLevelIndex >= 0"
        />
        <c-drawer-component
          v-for="(component, index) in engine.components.topLevel"
          :key="component.address.toString()"
          :active-after-me="activeTopLevelIndex > index"
          :address="component.address"
          :component
          :filter="componentFilter"
          :has-following-sibling="index < engine.components.topLevel.length - 1"
        />
      </template>
    </div>

    <c-separator />
    <div class="flex-none">
      <c-dropdown-menu
        v-if="engine.auth.isAdmin"
        :content="{ side: 'right', align: 'start' }"
        :items="adminItems"
      >
        <div :class="footerRowClass">
          <c-icon class="size-5" :name="icons.admin" />
          <span class="grow text-left">Admin</span>
          <c-icon class="size-5" :name="icons.menuRight" />
        </div>
      </c-dropdown-menu>
      <button v-if="engine.auth.isAdmin" :class="footerRowClass" @click="promptReload">
        <c-icon class="size-5" :name="icons.configuration" />
        <span class="grow text-left">Reload Configuration</span>
      </button>

      <c-popover :content="{ side: 'right', align: 'end' }" :ui="{ content: 'w-[350px]' }">
        <div :class="footerRowClass">
          <c-icon class="size-5" :name="icons.preferences" />
          <span class="grow text-left">Preferences</span>
          <c-icon class="size-5" :name="icons.menuRight" />
        </div>
        <template #content>
          <div class="flex items-center justify-evenly gap-3 p-3">
            <c-switch v-model="preferences.isDarkModeEnabled" label="Dark Mode" />
            <c-switch
              v-if="isDevelopment"
              v-model="preferences.isDeveloperModeEnabled"
              label="Developer Mode"
            />
          </div>
          <c-separator />
          <div class="p-3">
            <c-form-field
              hint="The time over which statistics, like alert counts, are calculated."
              label="Statistics Duration"
            >
              <c-select-menu
                v-model="preferences.statisticsDuration"
                class="w-full"
                :items="statisticsDurations"
                :search-input="false"
              >
                <template #default>{{ displayDuration(preferences.statisticsDuration) }}</template>
                <template #item-label="{ item }">{{ displayDuration(item) }}</template>
              </c-select-menu>
            </c-form-field>
          </div>
        </template>
      </c-popover>

      <!-- Everything here is a development tool, which the engine warns should only be turned on
      while developing. So the whole section follows the one switch that says whether these are
      wanted, rather than a menu that stays put while emptying out. -->
      <template v-if="isDeveloperMode">
        <c-separator />
        <c-dropdown-menu :content="{ side: 'right', align: 'end' }" :items="developerItems">
          <div :class="footerRowClass">
            <c-icon class="size-5" :name="icons.developer" />
            <span class="grow text-left">Developer</span>
            <c-icon class="size-5" :name="icons.menuRight" />
          </div>
        </c-dropdown-menu>
      </template>

      <!-- Impersonating is a state the whole console is in, so getting back out of it stays at the
      top level rather than inside the menu that started it. -->
      <template v-if="engine.auth.isImpersonating">
        <c-separator />
        <button :class="footerRowClass" @click="stopImpersonating">
          <c-icon class="text-warning size-5" :name="icons.viewer" />
          <span class="grow text-left">
            Impersonating {{ engine.auth.user?.username }}
            <c-text variant="description">Return to your own account.</c-text>
          </span>
        </button>
      </template>

      <c-separator />
      <nuxt-link :class="footerRowClass" :to="engine.auth.user == null ? '/login' : '/account'">
        <c-icon class="size-5" :name="icons.user" />
        <span class="grow text-left">
          {{ engine.auth.user != null ? engine.auth.user.username : 'Login' }}
        </span>
        <c-tooltip
          v-if="engine.auth.user?.admin"
          text="You are logged in with administrative access."
        >
          <c-badge color="primary" :icon="icons.admin" size="sm">Admin</c-badge>
        </c-tooltip>
      </nuxt-link>
    </div>
  </aside>
</template>
