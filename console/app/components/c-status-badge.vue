<script lang="ts" setup>
import { upperFirst } from 'lodash-es'

import { useAccess } from '@/api/access'
import type { Address } from '@/api/address'
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import type { Connectivity } from '@/api/shared'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { componentCount, countStatuses } from '@/statuses'
import { debouncedComputed } from '@/utilities'

// Without an address the badge covers every component in the engine, which is how the drawer
// header summarizes and controls the whole tree.
const { address = null, scale = 0.55 } = defineProps<{
  address?: Address | null
  scale?: number
}>()

const engine = useEngine()
const access = useAccess()
const notify = useNotify()

const selector = $computed(() => address?.all() ?? new AddressSelector('@:all'))

// Everything the badge covers, the subject itself plus everything below it.
const scope = $computed(() => {
  if (address == null) {
    return engine.components.all.map((component) => component.address)
  }

  return [address, ...engine.components.getDescendants(address).map((child) => child.address)]
})

const states = $(
  debouncedComputed(
    () =>
      countStatuses(
        scope.map((target) => ({
          status: engine.statuses.get(target),
          operable: access.canOperate(target.toString()),
        })),
      ),
    250,
  ),
)

// The "All" variants and their counters only make sense once more than the subject itself is
// affected.
const hasDescendants = $computed(() => states.total > 1)

// An addressed badge reports its own component's state, the aggregate reports whether anything
// it covers is running or enabled.
const status = $computed(() => {
  const own = address != null ? engine.statuses.get(address) : null
  return {
    running: address != null ? (own?.running ?? null) : states.anyRunning,
    enabled: address != null ? (own?.enabled ?? null) : states.anyEnabled,
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

const isReadonly = $computed(() => !canControl && engine.auth.user != null)

const readonlyMessage = $computed(() =>
  address != null
    ? 'You have permissions to view this component, but not to control it.'
    : 'You have permissions to view these components, but not to control them.',
)

const subject = $computed(() => (address != null ? `"${address}"` : 'all components'))

const connectivityColors: Record<Connectivity, string> = {
  connected: 'bg-success',
  connecting: 'bg-warning',
  disconnected: 'bg-error',
}

// A stopped component's connections are expectedly down, so they show inert grey rather than the
// alarming red reserved for failures while running.
function connectivityColor(connectivity: Connectivity): string {
  return status.running === true ? connectivityColors[connectivity] : 'bg-inverted/40'
}

// Segments drawn in the connectivity indicator: a single overall state when the component defines
// its own `__connectivity__`, otherwise one segment per connection.
const connectionSegments = $computed<Connectivity[]>(() => {
  if (status.connectivity != null) {
    return [status.connectivity]
  }

  return status.connections.map((connection) => connection.connectivity)
})

// Keep the indicator's size proportional to the badge, which renders at 0.55 scale by default
// with an 8px indicator and a 4px hit-area extension on every side.
const connectivitySize = $computed(() => `${Math.round((8 * scale) / 0.55)}px`)
const connectivityHitInset = $computed(() => `${-Math.round((4 * scale) / 0.55)}px`)

// The menu stays open through an action so several can be run in a row, the outcome of each one
// is reported as a toast.
async function perform(action: () => unknown, success: string, failure: string) {
  await guard(Promise.resolve(action()), () => {
    notify.error(failure)
  })

  notify.success(success)
}

function start() {
  return perform(() => engine.start(address!), `${subject} started.`, `Failed to start ${subject}.`)
}

function startAll() {
  return perform(
    () => engine.start(selector),
    `${componentCount(states.stopped)} started.`,
    `Failed to start ${subject} and everything below it.`,
  )
}

// Stopping a component cascades to its descendants, so one call covers both variants.
function stop() {
  return perform(
    () => engine.stop(address ?? selector),
    hasDescendants ? `${componentCount(states.running)} stopped.` : `${subject} stopped.`,
    `Failed to stop ${subject}.`,
  )
}

function enable() {
  return perform(
    () => engine.enable(address!),
    `${subject} enabled.`,
    `Failed to enable ${subject}.`,
  )
}

function enableAll() {
  return perform(
    () => engine.enable(selector),
    `${componentCount(states.disabled)} enabled.`,
    `Failed to enable ${subject} and everything below it.`,
  )
}

function disable() {
  return perform(
    () => engine.disable(address!),
    `${subject} disabled.`,
    `Failed to disable ${subject}.`,
  )
}

function disableAll() {
  return perform(
    () => engine.disable(selector),
    `${componentCount(states.enabled)} disabled.`,
    `Failed to disable ${subject} and everything below it.`,
  )
}

const rowClass = 'flex min-h-[26px] items-center gap-2 px-2.5 py-0.5'
</script>

<template>
  <!-- The whole cluster is the hover target, and the leading slot puts a caller's own indicators
  inside it so one hover reaches the menu from anywhere along the row. -->
  <c-popover
    :close-delay="200"
    :content="{ side: 'bottom', align: 'start', sideOffset: 6 }"
    enable-touch
    mode="hover"
    :ui="{ content: 'w-auto p-0' }"
  >
    <div class="flex cursor-pointer items-center">
      <slot name="leading" />
      <div v-if="connectionSegments.length > 0" class="relative mr-2 flex">
        <!-- Invisible hit-area extension so the small indicator stays comfortable to hover. -->
        <span class="absolute" :style="{ inset: connectivityHitInset }" />
        <!-- One vertical segment per connection so mixed states stay visible at a glance. -->
        <div
          class="flex overflow-hidden rounded-full"
          :style="{ width: connectivitySize, height: connectivitySize }"
        >
          <span
            v-for="(connectivity, index) in connectionSegments"
            :key="index"
            :class="[
              $style.segment,
              !status.running && $style.still,
              connectivityColor(connectivity),
            ]"
          />
        </div>
      </div>
      <span class="relative inline-flex">
        <span
          :class="[
            $style.badge,
            status.running && $style.running,
            status.enabled && $style.enabled,
          ]"
          :style="{ scale: String(scale) }"
        />
        <c-icon
          v-if="isReadonly"
          class="absolute -top-0.5 -right-0.5 size-1.5 opacity-70"
          :name="icons.locked"
        />
      </span>
    </div>

    <template #content>
      <div class="min-w-40 py-1">
        <div class="flex items-center justify-between px-2.5 pt-1 pb-0.5">
          <c-text variant="description">Status</c-text>
          <c-tooltip v-if="isReadonly" :text="readonlyMessage">
            <c-icon class="ml-4 size-2.5" :name="icons.locked" />
          </c-tooltip>
        </div>

        <!-- Each state row flies its actions out beside it, so the menu reads as the state first
        and what can be done about it second. A viewer gets no flyout, which `open` pins shut
        while `undefined` leaves the hover card to run itself. -->
        <!-- Kept in place rather than portaled, so that reaching the flyout still counts as
        hovering the menu it came from. Portaled to the body it sits outside that menu, and the
        pointer arriving on it reads as the pointer having left, closing the whole stack. -->
        <c-popover
          v-if="status.running != null"
          :close-delay="300"
          :content="{ side: 'right', align: 'start', sideOffset: 0 }"
          enable-touch
          mode="hover"
          :open="canControl ? undefined : false"
          :portal="false"
          :ui="{ content: 'w-auto p-0' }"
        >
          <div :class="[rowClass, canControl && 'hover:bg-elevated cursor-pointer']">
            <c-icon
              class="size-3.5"
              :class="status.running ? 'text-success' : 'text-dimmed'"
              :name="status.running ? icons.start : icons.stop"
            />
            <span class="grow text-sm">{{ status.running ? 'Running' : 'Stopped' }}</span>
            <c-badge v-if="hasDescendants" color="neutral" size="sm" variant="subtle">
              {{ status.running ? states.running : states.stopped }}
            </c-badge>
            <c-icon v-if="canControl" class="size-4" :name="icons.menuRight" />
          </div>
          <template #content>
            <div class="min-w-32 py-1">
              <button
                v-if="address != null && !hasDescendants && !status.running"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="start"
              >
                <c-icon class="size-3.5 text-success" :name="icons.start" />
                <span class="grow text-left text-sm">Start</span>
              </button>
              <button
                v-if="hasDescendants && !states.allRunning"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="startAll"
              >
                <c-icon class="size-3.5 text-success" :name="icons.start" />
                <span class="grow text-left text-sm">Start All</span>
                <c-badge color="neutral" size="sm" variant="subtle">{{ states.stopped }}</c-badge>
              </button>
              <button
                v-if="states.someRunning"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="stop"
              >
                <c-icon class="size-3.5 text-error" :name="icons.stop" />
                <span class="grow text-left text-sm">
                  {{ hasDescendants ? 'Stop All' : 'Stop' }}
                </span>
                <c-badge v-if="hasDescendants" color="neutral" size="sm" variant="subtle">
                  {{ states.running }}
                </c-badge>
              </button>
            </div>
          </template>
        </c-popover>

        <c-popover
          v-if="status.enabled != null"
          :close-delay="150"
          :content="{ side: 'right', align: 'start', sideOffset: 6 }"
          enable-touch
          mode="hover"
          :open="canControl ? undefined : false"
          :ui="{ content: 'w-auto p-0' }"
        >
          <div :class="[rowClass, canControl && 'hover:bg-elevated cursor-pointer']">
            <c-icon
              class="size-3.5"
              :class="status.enabled ? 'text-primary' : 'text-dimmed'"
              :name="status.enabled ? icons.enable : icons.disable"
            />
            <span class="grow text-sm">{{ status.enabled ? 'Enabled' : 'Disabled' }}</span>
            <c-badge v-if="hasDescendants" color="neutral" size="sm" variant="subtle">
              {{ status.enabled ? states.enabled : states.disabled }}
            </c-badge>
            <c-icon v-if="canControl" class="size-4" :name="icons.menuRight" />
          </div>
          <template #content>
            <div class="min-w-32 py-1">
              <button
                v-if="address != null && !status.enabled"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="enable"
              >
                <c-icon class="size-3.5 text-success" :name="icons.enable" />
                <span class="grow text-left text-sm">Enable</span>
              </button>
              <button
                v-if="hasDescendants && !states.allEnabled"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="enableAll"
              >
                <c-icon class="size-3.5 text-success" :name="icons.enable" />
                <span class="grow text-left text-sm">Enable All</span>
                <c-badge color="neutral" size="sm" variant="subtle">{{ states.disabled }}</c-badge>
              </button>
              <button
                v-if="address != null && status.enabled"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="disable"
              >
                <c-icon class="size-3.5 text-warning" :name="icons.disable" />
                <span class="grow text-left text-sm">Disable</span>
              </button>
              <button
                v-if="hasDescendants && states.someEnabled"
                :class="[rowClass, 'hover:bg-elevated w-full cursor-pointer']"
                @click="disableAll"
              >
                <c-icon class="size-3.5 text-warning" :name="icons.disable" />
                <span class="grow text-left text-sm">Disable All</span>
                <c-badge color="neutral" size="sm" variant="subtle">{{ states.enabled }}</c-badge>
              </button>
            </div>
          </template>
        </c-popover>

        <template v-if="status.connectivity != null || status.connections.length > 0">
          <c-separator class="mt-1" />
          <div class="px-2.5 pt-1 pb-0.5">
            <c-text variant="description">Connections</c-text>
          </div>
        </template>
        <div v-if="status.connectivity != null" :class="rowClass">
          <c-tooltip :text="upperFirst(status.connectivity)">
            <span
              :class="[
                $style.dot,
                !status.running && $style.still,
                connectivityColor(status.connectivity),
              ]"
            />
          </c-tooltip>
          <span class="text-sm">Component</span>
        </div>
        <div
          v-for="connection in status.connections"
          :key="connection.name"
          :class="[rowClass, 'items-start']"
        >
          <c-tooltip :text="upperFirst(connection.connectivity)">
            <span
              :class="[
                $style.dot,
                'mt-1.5',
                !status.running && $style.still,
                connectivityColor(connection.connectivity),
              ]"
            />
          </c-tooltip>
          <div>
            <div class="text-sm">{{ connection.name }}</div>
            <c-text variant="description">{{ connection.label }}</c-text>
          </div>
        </div>
      </div>
    </template>
  </c-popover>
</template>

<style module>
.segment {
  flex: 1;
  animation: pulse 2s ease-in-out infinite;
}

.segment:not(:last-child) {
  margin-right: 1px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

/* A stopped component's indicator holds still, the pulse implies liveness it does not have. */
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

/* The badge is a dot inside a dotted ring, the dot saying whether the component runs and the ring
whether it is enabled. */
.badge {
  position: relative;
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background-color: var(--ui-text-dimmed);
  outline: 3.5px dotted var(--ui-text-dimmed);
}

/* Extend the hover target a few pixels past the dotted ring without changing the visible badge. */
.badge::after {
  content: '';
  position: absolute;
  inset: -8px;
}

.running.running.running {
  background-color: var(--ui-primary);
  animation: roll 5s linear infinite;
}

.enabled.enabled.enabled {
  outline-color: var(--ui-primary);
}

@keyframes roll {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}
</style>
