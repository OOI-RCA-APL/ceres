<script lang="ts" setup>
import { useDialogPluginComponent } from 'quasar'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import StatusBadgeAffectedCounter from '@/components/StatusBadgeAffectedCounter.vue'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { debouncedComputed } from '@/utilities'

const { address, kind } = defineProps<{
  address: Address
  kind: 'run' | 'enable'
}>()

defineEmits([...useDialogPluginComponent.emits])

const engine = useEngine()
const notify = useNotify()

const { dialogRef, onDialogHide, onDialogOK } = useDialogPluginComponent()

const status = $computed(() => ({
  running: engine.statuses.get(address)?.running ?? null,
  enabled: engine.statuses.get(address)?.enabled ?? null,
}))

const descendants = $computed(() => engine.components.getDescendants(address))
const states = $(
  debouncedComputed(() => {
    let running = status.running ? 1 : 0
    let enabled = status.enabled ? 1 : 0

    for (const descendant of descendants) {
      const descendantStatus = engine.statuses.get(descendant.address)
      if (descendantStatus) {
        if (descendantStatus.running) {
          running++
        }
        if (descendantStatus.enabled) {
          enabled++
        }
      }
    }

    const total = descendants.length + 1
    return {
      running,
      stopped: total - running,
      enabled,
      disabled: total - enabled,
      total,
      allRunning: running === total,
      someRunning: running > 0,
      allEnabled: enabled === total,
      someEnabled: enabled > 0,
    }
  }, 250)
)

// The subtitle states where the component stands before any choice is made.
const stateText = $computed(() => {
  if (kind === 'run') {
    if (descendants.length > 0) {
      return `${states.running} of ${states.total} components running`
    }

    return status.running ? 'Running' : 'Stopped'
  }

  if (descendants.length > 0) {
    return `${states.enabled} of ${states.total} components enabled`
  }

  return status.enabled ? 'Enabled' : 'Disabled'
})

async function perform(action: () => unknown, success: string, failure: string) {
  onDialogOK()
  await guard(Promise.resolve(action()), () => {
    notify.error(failure)
  })
  notify.success(success)
}

function start() {
  return perform(
    () => engine.start(address),
    `Started "${address}".`,
    `Failed to start "${address}".`
  )
}

function startAll() {
  return perform(
    () => engine.start(address.all()),
    `Started ${states.stopped} components.`,
    `Failed to start "${address}" and its descendants.`
  )
}

function stop() {
  return perform(
    () => engine.stop(address),
    descendants.length > 0 ? `Stopped ${states.running} components.` : `Stopped "${address}".`,
    `Failed to stop "${address}".`
  )
}

function enable() {
  return perform(
    () => engine.enable(address),
    `Enabled "${address}".`,
    `Failed to enable "${address}".`
  )
}

function enableAll() {
  return perform(
    () => engine.enable(address.all()),
    `Enabled ${states.disabled} components.`,
    `Failed to enable "${address}" and its descendants.`
  )
}

function disable() {
  return perform(
    () => engine.disable(address),
    `Disabled "${address}".`,
    `Failed to disable "${address}".`
  )
}

function disableAll() {
  return perform(
    () => engine.disable(address.all()),
    `Disabled ${states.enabled} components.`,
    `Failed to disable "${address}" and its descendants.`
  )
}
</script>

<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card bordered class="q-dialog-plugin" flat>
      <div class="items-center no-wrap q-pl-md q-pr-sm row">
        <common-text element="h2" variant="title1">{{ address.toString() }}</common-text>
        <q-space />
        <span :class="['q-mr-sm', 'text-grey-6', $style.state]">{{ stateText }}</span>
        <q-btn v-close-popup dense flat icon="close" round />
      </div>
      <q-list class="q-pb-sm q-pt-xs" dense>
        <template v-if="kind === 'run'">
          <q-item
            v-if="descendants.length === 0 && !status.running"
            :class="$style.item"
            clickable
            @click="start"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-positive']">
              <q-icon :name="icons.start" size="14px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Start</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="descendants.length > 0 && !states.allRunning"
            :class="$style.item"
            clickable
            @click="startAll"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-positive']">
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
          <q-item v-if="states.someRunning" :class="$style.item" clickable @click="stop">
            <q-item-section avatar :class="[$style.avatar, 'text-negative']">
              <q-icon :name="icons.stop" size="14px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ descendants.length > 0 ? 'Stop All' : 'Stop' }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="descendants.length > 0" side>
              <status-badge-affected-counter>
                {{ states.running }}
              </status-badge-affected-counter>
            </q-item-section>
          </q-item>
        </template>
        <template v-else>
          <q-item
            v-if="descendants.length === 0 && !status.enabled"
            :class="$style.item"
            clickable
            @click="enable"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-positive']">
              <q-icon :name="icons.enable" size="14px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Enable</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="descendants.length > 0 && !states.allEnabled"
            :class="$style.item"
            clickable
            @click="enableAll"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-positive']">
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
            v-if="descendants.length === 0 && status.enabled"
            :class="$style.item"
            clickable
            @click="disable"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-warning']">
              <q-icon :name="icons.disable" size="14px" />
            </q-item-section>
            <q-item-section>
              <q-item-label>Disable</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="descendants.length > 0 && states.someEnabled"
            :class="$style.item"
            clickable
            @click="disableAll"
          >
            <q-item-section avatar :class="[$style.avatar, 'text-warning']">
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
        </template>
      </q-list>
    </q-card>
  </q-dialog>
</template>

<style lang="scss" module>
.state {
  font-size: 13px;
}

.item {
  min-height: 28px;
  padding: 4px 16px;
}

.avatar {
  min-width: 14px;
  align-items: center;
  padding-right: 8px;
}
</style>
