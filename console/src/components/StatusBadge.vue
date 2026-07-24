<script lang="ts" setup>
import { upperFirst } from 'lodash-es'

import { useAccess } from '@/api/access'
import { Address, AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import StatusBadgeAffectedCounter from '@/components/StatusBadgeAffectedCounter.vue'
import { useStatusMenu } from '@/components/status-menu'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

// Without an address the badge covers every component in the engine, which is how the drawer
// header summarizes and controls the whole tree.
const { address = null, scale = 0.55 } = defineProps<{
  address?: Address | null
  scale?: number
}>()

const engine = useEngine()
const access = useAccess()
const menu = useStatusMenu()

const selector = $computed(() => address?.all() ?? new AddressSelector('@:all'))

// Everything the badge covers, the subject itself plus everything below it.
const scope = $computed(() => {
  if (address == null) {
    return engine.components.all.map((component) => component.address)
  }

  return [address, ...engine.components.getDescendants(address).map((child) => child.address)]
})

const states = $(
  debouncedComputed(() => {
    // Counts and actions only cover components the user may operate, while the aggregate badge
    // still reflects everything it covers.
    let running = 0
    let enabled = 0
    let total = 0
    let anyRunning = false
    let anyEnabled = false

    for (const target of scope) {
      const targetStatus = engine.statuses.get(target)
      if (targetStatus == null) {
        continue
      }

      if (targetStatus.running) {
        anyRunning = true
      }
      if (targetStatus.enabled) {
        anyEnabled = true
      }

      if (!access.canOperate(target.toString())) {
        continue
      }

      total++
      if (targetStatus.running) {
        running++
      }
      if (targetStatus.enabled) {
        enabled++
      }
    }

    return {
      running,
      stopped: total - running,
      enabled,
      disabled: total - enabled,
      total,
      anyRunning,
      anyEnabled,
      allRunning: total > 0 && running === total,
      someRunning: running > 0,
      allEnabled: total > 0 && enabled === total,
      someEnabled: enabled > 0,
    }
  }, 250)
)

// The "All" variants and their counters only make sense once more than the subject itself is
// affected.
const hasDescendants = $computed(() => states.total > 1)

// An addressed badge reports its own component's state, the aggregate reports whether anything
// it covers is running or enabled.
const status = $computed(() => {
  const own = address != null ? engine.statuses.get(address) : null
  return {
    running: address != null ? own?.running ?? null : states.anyRunning,
    enabled: address != null ? own?.enabled ?? null : states.anyEnabled,
    connectivity: own?.connectivity ?? null,
    connections: own?.connections ?? [],
  }
})

const canControl = $computed(() => {
  if (address != null) {
    return access.canOperate(address.toString())
  }

  return engine.components.all.some((component) => access.canOperate(component.address.toString()))
})

const readonly = $computed(() => !canControl && engine.auth.user != null)

const readonlyMessage = $computed(() =>
  address != null
    ? 'You have permissions to view this component, but not to control it.'
    : 'You have permissions to view these components, but not to control them.'
)

const subject = $computed(() => (address != null ? `"${address}"` : 'all components'))

function count(total: number) {
  return `${total} component${total === 1 ? '' : 's'}`
}

const connectivityColors: Record<Connectivity, string> = {
  connected: 'positive',
  connecting: 'warning',
  disconnected: 'negative',
}

// A stopped component's connections are expectedly down, so they show inert grey rather than the
// alarming red reserved for failures while running.
function connectivityColor(connectivity: Connectivity): string {
  return status.running === true ? connectivityColors[connectivity] : 'grey'
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

// Keep the indicator's size proportional to the badge, which renders at 0.55 scale by default
// with an 8px indicator and a 4px hit-area extension on every side.
const connectivitySize = $computed(() => `${Math.round((8 * scale) / 0.55)}px`)
const connectivityHitInset = $computed(() => `${-Math.round((4 * scale) / 0.55)}px`)

function openSubmenu(kind: 'run' | 'enable') {
  if (canControl) {
    menu.openSubmenu(kind)
  }
}

// Surrounding rows can widen the hover target by driving the menu themselves, so a badge without
// a connectivity indicator is no harder to reach than one with it.
defineExpose({ menu })

function start() {
  return menu.perform(
    () => engine.start(address!),
    `${subject} started.`,
    `Failed to start ${subject}.`
  )
}

function startAll() {
  return menu.perform(
    () => engine.start(selector),
    `${count(states.stopped)} started.`,
    `Failed to start ${subject} and everything below it.`
  )
}

// Stopping a component cascades to its descendants, so one call covers both variants.
function stop() {
  return menu.perform(
    () => engine.stop(address ?? selector),
    hasDescendants ? `${count(states.running)} stopped.` : `${subject} stopped.`,
    `Failed to stop ${subject}.`
  )
}

function enable() {
  return menu.perform(
    () => engine.enable(address!),
    `${subject} enabled.`,
    `Failed to enable ${subject}.`
  )
}

function enableAll() {
  return menu.perform(
    () => engine.enable(selector),
    `${count(states.disabled)} enabled.`,
    `Failed to enable ${subject} and everything below it.`
  )
}

function disable() {
  return menu.perform(
    () => engine.disable(address!),
    `${subject} disabled.`,
    `Failed to disable ${subject}.`
  )
}

function disableAll() {
  return menu.perform(
    () => engine.disable(selector),
    `${count(states.enabled)} disabled.`,
    `Failed to disable ${subject} and everything below it.`
  )
}
</script>

<template>
  <div
    :class="['items-center', 'no-wrap', 'row', $style.cluster]"
    @click.stop.prevent="menu.onEnter"
    @mouseenter="menu.onEnter"
    @mouseleave="menu.onLeave"
  >
    <div v-if="hasConnectivity" :class="[$style.connectivity, 'q-mr-sm']">
      <span :class="$style.connectivityHit" :style="{ inset: connectivityHitInset }" />
      <div
        :class="$style.connectivityShape"
        :style="{ width: connectivitySize, height: connectivitySize }"
      >
        <span
          v-for="(connectivity, index) in connectionSegments"
          :key="index"
          :class="[
            $style.segment,
            !status.running && $style.still,
            `bg-${connectivityColor(connectivity)}`,
          ]"
        />
      </div>
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
        <q-menu
          v-model="menu.isOpen"
          anchor="bottom right"
          no-focus
          no-parent-event
          :offset="[-4, 6]"
          self="top left"
        >
          <q-card bordered flat @mouseenter="menu.cancelClose" @mouseleave="menu.onLeave">
            <q-list dense>
              <q-item-label :class="$style.sectionHeader" header>
                <span>Status</span>
                <span v-if="readonly" :class="$style.readonlyTag">
                  <q-icon name="lock" size="10px">
                    <q-tooltip anchor="top middle" self="bottom middle">
                      {{ readonlyMessage }}
                    </q-tooltip>
                  </q-icon>
                </span>
              </q-item-label>
              <q-item
                v-if="status.running != null"
                :class="$style.menuRow"
                :clickable="canControl"
                @click="openSubmenu('run')"
                @mouseenter="openSubmenu('run')"
                @mouseleave="menu.onRowLeave"
              >
                <q-item-section
                  avatar
                  :class="[$style.stateAvatar, status.running ? 'text-positive' : 'text-grey']"
                >
                  <q-icon :name="status.running ? icons.start : icons.stop" size="14px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ status.running ? 'Running' : 'Stopped' }}</q-item-label>
                </q-item-section>
                <q-item-section v-if="hasDescendants" side>
                  <status-badge-affected-counter>
                    {{ status.running ? states.running : states.stopped }}
                  </status-badge-affected-counter>
                </q-item-section>
                <q-item-section v-if="canControl" side>
                  <q-icon :name="icons.menuRight" size="16px" />
                </q-item-section>
                <q-menu
                  v-if="canControl"
                  v-model="menu.runSubmenuIsOpen"
                  anchor="top end"
                  no-focus
                  no-parent-event
                  :offset="[6, 0]"
                  self="top start"
                >
                  <q-card
                    bordered
                    flat
                    @mouseenter="menu.onSubmenuEnter"
                    @mouseleave="menu.onSubmenuLeave"
                  >
                    <q-list dense>
                      <q-item
                        v-if="address != null && !hasDescendants && !status.running"
                        :class="$style.menuRow"
                        clickable
                        @click="start"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-positive']">
                          <q-icon :name="icons.start" size="14px" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Start</q-item-label>
                        </q-item-section>
                      </q-item>
                      <q-item
                        v-if="hasDescendants && !states.allRunning"
                        :class="$style.menuRow"
                        clickable
                        @click="startAll"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-positive']">
                          <q-icon :name="icons.start" size="14px" />
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
                      <q-item
                        v-if="states.someRunning"
                        :class="$style.menuRow"
                        clickable
                        @click="stop"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-negative']">
                          <q-icon :name="icons.stop" size="14px" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>{{ hasDescendants ? 'Stop All' : 'Stop' }}</q-item-label>
                        </q-item-section>
                        <q-item-section v-if="hasDescendants" side>
                          <status-badge-affected-counter>
                            {{ states.running }}
                          </status-badge-affected-counter>
                        </q-item-section>
                      </q-item>
                    </q-list>
                  </q-card>
                </q-menu>
              </q-item>
              <q-item
                v-if="status.enabled != null"
                :class="$style.menuRow"
                :clickable="canControl"
                @click="openSubmenu('enable')"
                @mouseenter="openSubmenu('enable')"
                @mouseleave="menu.onRowLeave"
              >
                <q-item-section
                  avatar
                  :class="[$style.stateAvatar, status.enabled ? 'text-primary' : 'text-grey']"
                >
                  <q-icon :name="status.enabled ? icons.enable : icons.disable" size="14px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ status.enabled ? 'Enabled' : 'Disabled' }}</q-item-label>
                </q-item-section>
                <q-item-section v-if="hasDescendants" side>
                  <status-badge-affected-counter>
                    {{ status.enabled ? states.enabled : states.disabled }}
                  </status-badge-affected-counter>
                </q-item-section>
                <q-item-section v-if="canControl" side>
                  <q-icon :name="icons.menuRight" size="16px" />
                </q-item-section>
                <q-menu
                  v-if="canControl"
                  v-model="menu.enableSubmenuIsOpen"
                  anchor="top end"
                  no-focus
                  no-parent-event
                  :offset="[6, 0]"
                  self="top start"
                >
                  <q-card
                    bordered
                    flat
                    @mouseenter="menu.onSubmenuEnter"
                    @mouseleave="menu.onSubmenuLeave"
                  >
                    <q-list dense>
                      <q-item
                        v-if="address != null && !status.enabled"
                        :class="$style.menuRow"
                        clickable
                        @click="enable"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-positive']">
                          <q-icon :name="icons.enable" size="14px" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Enable</q-item-label>
                        </q-item-section>
                      </q-item>
                      <q-item
                        v-if="hasDescendants && !states.allEnabled"
                        :class="$style.menuRow"
                        clickable
                        @click="enableAll"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-positive']">
                          <q-icon :name="icons.enable" size="14px" />
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
                      <q-item
                        v-if="address != null && status.enabled"
                        :class="$style.menuRow"
                        clickable
                        @click="disable"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-warning']">
                          <q-icon :name="icons.disable" size="14px" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Disable</q-item-label>
                        </q-item-section>
                      </q-item>
                      <q-item
                        v-if="hasDescendants && states.someEnabled"
                        :class="$style.menuRow"
                        clickable
                        @click="disableAll"
                      >
                        <q-item-section avatar :class="[$style.stateAvatar, 'text-warning']">
                          <q-icon :name="icons.disable" size="14px" />
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
              </q-item>
              <template v-if="status.connectivity != null || status.connections.length > 0">
                <q-separator :class="$style.sectionSeparator" />
                <q-item-label :class="$style.sectionHeader" header>Connections</q-item-label>
              </template>
              <q-item v-if="status.connectivity != null" :class="$style.menuRow">
                <q-item-section avatar :class="$style.stateAvatar">
                  <span
                    :class="[
                      $style.dot,
                      !status.running && $style.still,
                      `bg-${connectivityColor(status.connectivity)}`,
                    ]"
                  >
                    <q-tooltip :class="`bg-${connectivityColor(status.connectivity)}`">
                      {{ upperFirst(status.connectivity) }}
                    </q-tooltip>
                  </span>
                </q-item-section>
                <q-item-section>
                  <q-item-label>Component</q-item-label>
                </q-item-section>
              </q-item>
              <q-item
                v-for="connection in status.connections"
                :key="connection.name"
                :class="$style.menuRow"
              >
                <q-item-section avatar :class="$style.stateAvatar">
                  <span
                    :class="[
                      $style.dot,
                      !status.running && $style.still,
                      `bg-${connectivityColor(connection.connectivity)}`,
                    ]"
                  >
                    <q-tooltip :class="`bg-${connectivityColor(connection.connectivity)}`">
                      {{ upperFirst(connection.connectivity) }}
                    </q-tooltip>
                  </span>
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ connection.name }}</q-item-label>
                  <q-item-label caption>{{ connection.label }}</q-item-label>
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
// The indicator keeps the same dot silhouette used in the flyout and connection lists, split into
// one vertical segment per connection so mixed states stay visible at a glance.
.cluster {
  cursor: pointer;
}

.connectivity {
  position: relative;
  display: flex;
}

// Invisible hit-area extension so the small indicator stays comfortable to hover and click.
.connectivityHit {
  position: absolute;
}

.connectivityShape {
  display: flex;
  border-radius: 50%;
  overflow: hidden;
}

.segment {
  flex: 1;
  animation: pulse 2s ease-in-out infinite;

  &:not(:last-child) {
    margin-right: 1px;
  }
}

.sectionHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px 2px;
  min-height: 0;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.4;
}

// The read-only marker sits in the header line so it never adds a row of its own.
.readonlyTag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 16px;
}

.sectionSeparator {
  margin-top: 4px;
}

.menuRow.menuRow {
  min-height: 26px;
  padding: 2px 10px;
}

.stateAvatar {
  min-width: 14px;
  align-items: center;
  padding-right: 8px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

// A stopped component's indicator holds still, the pulse implies liveness it does not have.
.still {
  animation: none;
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
