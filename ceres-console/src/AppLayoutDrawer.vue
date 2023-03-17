<template>
  <q-drawer v-model="drawer.isOpen" class="self-app-layout-drawer-root" :width="drawer.width">
    <div class="column full-height">
      <resize-handle
        v-model="drawer.width"
        class="self-resize-handle"
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
        <q-item clickable>
          <q-item-section avatar>
            <q-icon :name="icons.settings" />
          </q-item-section>
          <q-item-section avatar>
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

<script lang="ts" setup>
import { useConfig } from '@/api/operations'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useSettings } from '@/settings'
import { displayDuration } from '@/time'
import moment from 'moment'
import { useRoute } from 'vue-router'

const config = useConfig()
const drawer = useDrawer()
const route = useRoute()
const settings = useSettings()
</script>

<style lang="scss" scoped>
.self-app-layout-drawer-root {
  overflow: visible !important;
  position: relative;
}

.self-resize-handle {
  position: absolute;
  top: 0;
}
</style>
