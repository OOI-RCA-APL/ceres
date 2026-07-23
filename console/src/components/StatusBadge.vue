<script lang="ts" setup>
import { upperFirst } from 'lodash-es'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'

const { address, scale = 0.55 } = defineProps<{
  address: Address
  scale?: number
}>()

const engine = useEngine()
const access = useAccess()
const dialogs = useDialogs()

const status = $computed(() => ({
  running: engine.statuses.get(address)?.running ?? null,
  enabled: engine.statuses.get(address)?.enabled ?? null,
  connectivity: engine.statuses.get(address)?.connectivity ?? null,
  connections: engine.statuses.get(address)?.connections ?? [],
}))

const canControl = $computed(() => access.canOperate(address.toString()))
const readonly = $computed(() => !canControl && engine.auth.user != null)

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

// One menu covers the whole cluster, opening on hover or click anywhere over the indicator or
// badge. It summarizes the component's status, lists the applicable actions, and shows each
// connection's state. Leaving the cluster and menu closes it after a short grace period that lets
// the pointer cross the gap.
let badgeMenuIsOpen = $ref(false)
let badgeMenuCloseTimer: ReturnType<typeof setTimeout> | null = null

function cancelBadgeMenuClose() {
  if (badgeMenuCloseTimer != null) {
    clearTimeout(badgeMenuCloseTimer)
    badgeMenuCloseTimer = null
  }
}

function closeBadgeMenu() {
  cancelBadgeMenuClose()
  badgeMenuIsOpen = false
}

function onBadgeEnter() {
  cancelBadgeMenuClose()
  badgeMenuIsOpen = true
}

function onBadgeLeave() {
  cancelBadgeMenuClose()
  badgeMenuCloseTimer = setTimeout(closeBadgeMenu, 200)
}

// A state row opens the dialog holding its actions, closing the menu so the two never stack.
function openActions(kind: 'run' | 'enable') {
  closeBadgeMenu()
  dialogs.statusActions(address, kind)
}
</script>

<template>
  <div
    :class="['items-center', 'no-wrap', 'row', $style.cluster]"
    @click.stop.prevent="onBadgeEnter"
    @mouseenter="onBadgeEnter"
    @mouseleave="onBadgeLeave"
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
          v-model="badgeMenuIsOpen"
          anchor="bottom right"
          no-focus
          no-parent-event
          :offset="[-4, 6]"
          self="top left"
        >
          <q-card bordered flat @mouseenter="cancelBadgeMenuClose" @mouseleave="onBadgeLeave">
            <q-list dense>
              <q-item-label :class="$style.sectionHeader" header>Status</q-item-label>
              <q-item
                v-if="status.running != null"
                :class="$style.connectivityRow"
                :clickable="canControl"
                @click="canControl && openActions('run')"
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
                <q-item-section v-if="canControl" side>
                  <q-icon :name="icons.menuRight" size="16px" />
                </q-item-section>
              </q-item>
              <q-item
                v-if="status.enabled != null"
                :class="$style.connectivityRow"
                :clickable="canControl"
                @click="canControl && openActions('enable')"
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
                <q-item-section v-if="canControl" side>
                  <q-icon :name="icons.menuRight" size="16px" />
                </q-item-section>
              </q-item>
              <q-item v-if="readonly" :class="$style.connectivityRow">
                <q-item-section avatar :class="[$style.stateAvatar, 'text-grey-6']">
                  <q-icon name="lock" size="14px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label caption>Read-only</q-item-label>
                </q-item-section>
              </q-item>
              <template v-if="status.connectivity != null || status.connections.length > 0">
                <q-separator :class="$style.sectionSeparator" />
                <q-item-label :class="$style.sectionHeader" header>Connections</q-item-label>
              </template>
              <q-item v-if="status.connectivity != null" :class="$style.connectivityRow">
                <q-item-section avatar :class="$style.stateAvatar">
                  <span
                    :class="[
                      $style.dot,
                      !status.running && $style.still,
                      `bg-${connectivityColor(status.connectivity)}`,
                    ]"
                  >
                    <q-tooltip>{{ upperFirst(status.connectivity) }}</q-tooltip>
                  </span>
                </q-item-section>
                <q-item-section>
                  <q-item-label>Component</q-item-label>
                </q-item-section>
              </q-item>
              <q-item
                v-for="connection in status.connections"
                :key="connection.name"
                :class="$style.connectivityRow"
              >
                <q-item-section avatar :class="$style.stateAvatar">
                  <span
                    :class="[
                      $style.dot,
                      !status.running && $style.still,
                      `bg-${connectivityColor(connection.connectivity)}`,
                    ]"
                  >
                    <q-tooltip>{{ upperFirst(connection.connectivity) }}</q-tooltip>
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
  padding: 6px 10px 2px;
  min-height: 0;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.4;
}

.sectionSeparator {
  margin-top: 4px;
}

.connectivityRow.connectivityRow {
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
