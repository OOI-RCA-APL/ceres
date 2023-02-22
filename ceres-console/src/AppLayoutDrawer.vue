<template>
  <q-drawer v-model="drawer.isOpen" class="self-root" :width="drawer.width">
    <resize-handle
      v-model="drawer.width"
      class="self-resize-handle"
      direction="horizontal"
      :min="60"
      :style="{ left: `${drawer.width}px` }"
    />
    <div class="column full-height">
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
          <q-expansion-item v-model="drawer.isShowingUnits" :icon="icons.units" label="Units">
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
              <q-item-section no-wrap>
                <q-item-label class="text-no-wrap">{{ unit.name }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <alerts-indicator :unit-name="unit.name" />
              </q-item-section>
            </q-item>
          </q-expansion-item>
        </q-list>
      </div>
      <q-list>
        <q-item clickable @click="settings.isDarkModeEnabled = !settings.isDarkModeEnabled">
          <q-item-section avatar>
            <q-icon :name="settings.isDarkModeEnabled ? icons.darkMode : icons.lightMode" />
          </q-item-section>
          <q-item-section avatar>
            <q-item-label>{{ settings.isDarkModeEnabled ? 'Dark' : 'Light' }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </div>
  </q-drawer>
</template>

<script lang="ts" setup>
import { useConfig } from '@/api/queries'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useSettings } from '@/settings'
import { useRoute } from 'vue-router'

const config = useConfig()
const drawer = useDrawer()
const route = useRoute()
const settings = useSettings()
</script>

<style lang="scss" scoped>
.self-root {
  overflow: visible !important;
  position: relative;
}

.self-resize-handle {
  position: absolute;
  top: 0;
}
</style>
