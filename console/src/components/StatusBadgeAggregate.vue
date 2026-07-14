<script lang="ts" setup>
import { useAccess } from '@/api/access'
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import StatusBadgeAffectedCounter from '@/components/StatusBadgeAffectedCounter.vue'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const engine = useEngine()
const access = useAccess()

const components = $computed(() => engine.components.all)

const canControl = $computed(() =>
  components.some((component) => access.canOperate(component.address.toString()))
)
const readonly = $computed(() => !canControl && engine.auth.user != null)

let menuIsOpen = $ref(false)

const states = $(
  debouncedComputed(() => {
    let running = 0
    let stopped = 0
    let enabled = 0
    let disabled = 0

    for (const component of components) {
      const componentStatus = engine.statuses.get(component.address)
      if (componentStatus) {
        if (componentStatus.running) {
          running++
        } else {
          stopped++
        }
        if (componentStatus.enabled) {
          enabled++
        } else {
          disabled++
        }
      }
    }

    return {
      running,
      stopped,
      enabled,
      disabled,
      allRunning: running === components.length,
      someRunning: running > 0,
      allEnabled: enabled === components.length,
      someEnabled: enabled > 0,
    }
  }, 250)
)

const status = $computed(() => ({
  running: states.someRunning,
  enabled: states.someEnabled,
  connectivity: null,
}))

function startAll() {
  return engine.start(new AddressSelector('@:all'))
}

function stopAll() {
  return engine.stop(new AddressSelector('@:all'))
}

function enableAll() {
  return engine.enable(new AddressSelector('@:all'))
}

function disableAll() {
  return engine.disable(new AddressSelector('@:all'))
}
</script>

<template>
  <div class="items-center no-wrap row">
    <q-badge
      :class="[
        $style.root,
        status.running && $style.running,
        status.enabled && $style.enabled,
        canControl && 'cursor-pointer',
      ]"
      rounded
    >
      <q-tooltip
        v-if="!menuIsOpen && (status.running != null || status.enabled != null)"
        class="bg-primary text-white"
      >
        <span v-if="status.running != null">{{ status.running ? 'Running' : 'Stopped' }}</span>
        <template v-if="status.enabled != null">
          <span> &#x2E31; </span>
          <span>{{ status.enabled ? 'Enabled' : 'Disabled' }}</span>
        </template>
        <template v-if="readonly">
          <span> &#x2E31; </span>
          <span>Read-only</span>
        </template>
      </q-tooltip>
      <q-menu
        v-if="canControl"
        v-model="menuIsOpen"
        anchor="top right"
        class="relative-position"
        :offset="[12, 12]"
        self="top left"
      >
        <q-card bordered>
          <q-list dense>
            <q-item v-if="!states.allRunning && components.length > 0" clickable @click="startAll">
              <q-item-section avatar class="text-positive">
                <q-icon :name="icons.start" size="16px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Start All</q-item-label>
              </q-item-section>
              <q-item-section side>
                <status-badge-affected-counter>
                  {{ states.stopped }}
                </status-badge-affected-counter>
              </q-item-section>
            </q-item>
            <q-item v-show="states.someRunning" clickable @click="stopAll">
              <q-item-section avatar class="text-negative">
                <q-icon :name="icons.stop" size="16px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Stop All</q-item-label>
              </q-item-section>
              <q-item-section side>
                <status-badge-affected-counter>
                  {{ states.running }}
                </status-badge-affected-counter>
              </q-item-section>
            </q-item>
            <q-separator />
            <q-item v-if="!states.allEnabled && components.length > 0" clickable @click="enableAll">
              <q-item-section avatar class="text-positive">
                <q-icon :name="icons.enable" size="16px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Enable All</q-item-label>
              </q-item-section>
              <q-item-section side>
                <status-badge-affected-counter>
                  {{ states.disabled }}
                </status-badge-affected-counter>
              </q-item-section>
            </q-item>
            <q-item v-show="states.someEnabled" clickable @click="disableAll">
              <q-item-section avatar class="text-warning">
                <q-icon :name="icons.disable" size="16px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Disable All</q-item-label>
              </q-item-section>
              <q-item-section side>
                <status-badge-affected-counter>
                  {{ states.enabled }}
                </status-badge-affected-counter>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </q-menu>
    </q-badge>
    <q-icon v-if="readonly" :class="$style.lock" color="grey-6" name="lock" size="12px" />
  </div>
</template>

<style lang="scss" module>
.root {
  background-color: black;
  outline: 3.5px dotted black;
  scale: 0.55;
}

:global(.dark) .root {
  background-color: $grey-6;
  outline-color: $grey-6;
}

.running.running.running {
  background-color: $primary;
  animation: roll 5s linear infinite;
}

.enabled.enabled.enabled {
  outline-color: $primary;
}

@keyframes roll {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

.lock {
  margin-left: 2px;
  opacity: 0.7;
}
</style>
