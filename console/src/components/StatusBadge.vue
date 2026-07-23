<script lang="ts" setup>
import { upperFirst } from 'lodash-es'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import StatusBadgeAffectedCounter from '@/components/StatusBadgeAffectedCounter.vue'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const { address, scale = 0.55 } = defineProps<{
  address: Address
  scale?: number
}>()

const engine = useEngine()
const access = useAccess()

const status = $computed(() => ({
  running: engine.statuses.get(address)?.running ?? null,
  enabled: engine.statuses.get(address)?.enabled ?? null,
  connectivity: engine.statuses.get(address)?.connectivity ?? null,
  connections: engine.statuses.get(address)?.connections ?? [],
}))

const canControl = $computed(() => access.canOperate(address.toString()))
const readonly = $computed(() => !canControl && engine.auth.user != null)

let menuIsOpen = $ref(false)

const descendants = $computed(() => engine.components.getDescendants(address))
const states = $(
  debouncedComputed(() => {
    let running = status.running ? 1 : 0
    let stopped = status.running ? 0 : 1
    let enabled = status.enabled ? 1 : 0
    let disabled = status.enabled ? 0 : 1

    for (const descendant of descendants) {
      const descendantStatus = engine.statuses.get(descendant.address)
      if (descendantStatus) {
        if (descendantStatus.running) {
          running++
        } else {
          stopped++
        }
        if (descendantStatus.enabled) {
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
      allRunning: running === descendants.length + 1,
      someRunning: running > 0,
      allEnabled: enabled === descendants.length + 1,
      someEnabled: enabled > 0,
    }
  }, 250)
)

const connectivityColors: Record<Connectivity, string> = {
  connected: 'positive',
  connecting: 'warning',
  disconnected: 'negative',
}

// Segments drawn in the connectivity indicator: a single overall state when the component defines
// its own `__connectivity__`, otherwise one segment per connection.
const connectionSegments = $computed<Connectivity[]>(() => {
  if (status.connectivity != null) {
    return [status.connectivity]
  }

  return status.connections.map((connection) => connection.connectivity)
})

const hasConnectivity = $computed(() => connectionSegments.length > 0)
</script>

<template>
  <div class="items-center no-wrap row">
    <div v-if="hasConnectivity" :class="[$style.connectivity, 'q-mr-sm']">
      <div
        v-for="(connectivity, index) in connectionSegments"
        :key="index"
        :class="[$style.stripe, `bg-${connectivityColors[connectivity]}`]"
      />
      <q-tooltip :class="$style.connectivityTooltip">
        <q-list :class="$style.connectivityList" bordered dense separator>
          <q-item v-if="status.connectivity != null" :class="$style.connectivityRow">
            <q-item-section>
              <q-item-label>Component</q-item-label>
              <q-item-label caption>{{ upperFirst(status.connectivity) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <span :class="[$style.dot, `bg-${connectivityColors[status.connectivity]}`]" />
            </q-item-section>
          </q-item>
          <q-item
            v-for="connection in status.connections"
            :key="connection.name"
            :class="$style.connectivityRow"
          >
            <q-item-section>
              <q-item-label>{{ connection.name }}</q-item-label>
              <q-item-label caption>{{ upperFirst(connection.connectivity) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <span :class="[$style.dot, `bg-${connectivityColors[connection.connectivity]}`]" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-tooltip>
    </div>
    <span :class="$style.badgeWrapper">
      <q-badge
        :class="[
          $style.root,
          status.running && $style.running,
          status.enabled && $style.enabled,
          canControl && 'cursor-pointer',
        ]"
        rounded
        :style="{ scale: String(scale) }"
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
              <q-item v-if="!status.running" clickable @click="engine.start(address)">
                <q-item-section avatar class="text-positive">
                  <q-icon :name="icons.start" size="16px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Start</q-item-label>
                </q-item-section>
              </q-item>
              <q-item
                v-if="!states.allRunning && descendants.length > 0"
                clickable
                @click="engine.start(address.all())"
              >
                <q-item-section avatar class="text-positive">
                  <div class="items-center row">
                    <q-icon :name="icons.start" size="16px" />
                    <span :class="$style.allIcon">*</span>
                  </div>
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
              <q-item v-show="states.someRunning" clickable @click="engine.stop(address)">
                <q-item-section avatar class="text-negative">
                  <q-icon :name="icons.stop" size="16px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>
                    {{ descendants.length > 0 ? 'Stop All' : 'Stop' }}
                  </q-item-label>
                </q-item-section>
                <q-item-section v-if="descendants.length > 0" side>
                  <status-badge-affected-counter>
                    {{ states.running }}
                  </status-badge-affected-counter>
                </q-item-section>
              </q-item>
              <q-separator />
              <q-item v-if="!status.enabled" clickable @click="engine.enable(address)">
                <q-item-section avatar class="text-positive">
                  <q-icon :name="icons.enable" size="16px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Enable</q-item-label>
                </q-item-section>
              </q-item>
              <q-item
                v-if="!states.allEnabled && descendants.length > 0"
                clickable
                @click="engine.enable(address.all())"
              >
                <q-item-section avatar class="text-positive">
                  <div class="items-center row">
                    <q-icon :name="icons.enable" size="16px" />
                    <span :class="$style.allIcon">*</span>
                  </div>
                </q-item-section>
                <q-item-section>
                  <q-item-label>
                    <q-item-label>Enable All</q-item-label>
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <status-badge-affected-counter>
                    {{ states.disabled }}
                  </status-badge-affected-counter>
                </q-item-section>
              </q-item>
              <q-item v-else clickable @click="engine.disable(address)">
                <q-item-section avatar class="text-warning">
                  <q-icon :name="icons.disable" size="16px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>Disable</q-item-label>
                </q-item-section>
              </q-item>
              <q-item
                v-if="states.someEnabled && descendants.length > 0"
                clickable
                @click="engine.disable(address.all())"
              >
                <q-item-section avatar class="text-warning">
                  <div class="items-center row">
                    <q-icon :name="icons.disable" size="16px" />
                    <span :class="$style.allIcon">*</span>
                  </div>
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
      <q-icon v-if="readonly" :class="$style.lock" color="grey-6" name="lock" size="6px" />
    </span>
  </div>
</template>

<style lang="scss" module>
.connectivity {
  display: flex;
  width: 16px;
  height: 11px;
  border-radius: 2px;
  overflow: hidden;
  cursor: default;
}

.stripe {
  flex: 1;
  animation: pulse 2s ease-in-out infinite;

  &:not(:last-child) {
    border-right: 1px solid rgba(0, 0, 0, 0.55);
  }
}

.connectivityTooltip {
  padding: 4px;
  background: $dark;
}

.connectivityList {
  border-radius: 4px;
}

.connectivityRow {
  min-height: 26px;
  padding: 2px 10px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.65;
  }
}

.root {
  position: relative;
  background-color: black;
  outline: 3.5px dotted black;
}

// Extend the hover and click target a few pixels past the dotted outline without changing the
// visible badge.
.root::after {
  content: '';
  position: absolute;
  inset: -8px;
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

.allIcon {
  margin-top: 5px;
  margin-left: 2px;
}

.badgeWrapper {
  position: relative;
  display: inline-flex;
}

.lock {
  position: absolute;
  top: -2px;
  right: -2px;
  opacity: 0.7;
}
</style>
