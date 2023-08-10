<script lang="ts" setup>
import { Address } from '@/address'
import { disable, enable, start, stop, useStatuses } from '@/api/operations'

const { address } = defineProps<{
  address: Address
}>()

const statuses = useStatuses()
const status = $computed(() => ({
  running: statuses.get(address)?.running ?? null,
  enabled: statuses.get(address)?.enabled ?? null,
}))

let menuIsOpen = $ref(false)
</script>

<template>
  <q-badge
    :class="[
      $style.root,
      status.running && $style.running,
      status.enabled && $style.enabled,
      'cursor-pointer',
    ]"
    rounded
  >
    <q-tooltip
      v-if="!menuIsOpen && (status.running != null || status.enabled != null)"
      anchor="center right"
      class="bg-primary text-white"
      self="center left"
    >
      <span v-if="status.running != null">{{ status.running ? 'Running' : 'Stopped' }}</span>
      <span v-if="status.running != null && status.enabled != null"> ⸱ </span>
      <span>{{ status.enabled ? 'Enabled' : 'Disabled' }}</span>
    </q-tooltip>
    <q-menu v-model="menuIsOpen" anchor="top right" class="no-shadow" :offset="[8, 0]">
      <q-list bordered class="rounded-corners" dense>
        <q-item clickable @click="status.running ? stop(address) : start(address)">
          <q-item-section>
            <q-item-label>{{ status.running ? 'Stop' : 'Start' }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable @click="status.enabled ? disable(address) : enable(address)">
          <q-item-section>
            <q-item-label>{{ status.enabled ? 'Disable' : 'Enable' }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item clickable @click="start(address.all())">
          <q-item-section>
            <q-item-label>Start All</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item clickable @click="enable(address.all())">
          <q-item-section>
            <q-item-label>Enable All</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable @click="disable(address.all())">
          <q-item-section>
            <q-item-label>Disable All</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item :to="`/components/${address}`">
          <q-item-section>
            <q-item-label>View</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-badge>
</template>

<style lang="scss" module>
.root {
  background-color: transparent;
  outline: 3px solid black;
  scale: 0.5;
}

:global(.dark) .root {
  outline-color: white;
}

.running {
  background-color: $primary;
}

.enabled.enabled.enabled {
  outline-style: solid;
  outline-color: $primary;
}
</style>
