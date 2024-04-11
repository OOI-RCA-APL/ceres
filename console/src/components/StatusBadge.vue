<script lang="ts" setup>
import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { upperFirst } from 'lodash'

const { address } = defineProps<{
  address: Address
}>()

const engine = useEngine()

const status = $computed(() => ({
  running: engine.statuses.get(address)?.running ?? null,
  enabled: engine.statuses.get(address)?.enabled ?? null,
  connectivity: engine.statuses.get(address)?.connectivity ?? null,
}))

let menuIsOpen = $ref(false)

const connectionColor = $computed(() => {
  if (status.running !== true) {
    return 'grey'
  }
  if (status.connectivity === 'disconnected') {
    return 'negative'
  }
  if (status.connectivity === 'connecting') {
    return 'warning'
  }

  return 'primary'
})
</script>

<template>
  <div class="items-center no-wrap row">
    <q-icon
      v-if="status.connectivity != null"
      class="q-mr-sm"
      :color="connectionColor"
      :name="icons.connection"
      size="16px"
    >
      <q-tooltip :class="`bg-${connectionColor} text-white`">
        {{ upperFirst(status.connectivity) }}
      </q-tooltip>
    </q-icon>
    <q-badge
      :class="[
        $style.root,
        status.running && $style.running,
        status.enabled && $style.enabled,
        engine.auth.isOperator && 'cursor-pointer',
      ]"
      rounded
    >
      <q-tooltip
        v-if="!menuIsOpen && (status.running != null || status.enabled != null)"
        class="bg-primary text-white"
      >
        <span v-if="status.running != null">{{ status.running ? 'Running' : 'Stopped' }}</span>
        <template v-if="status.enabled != null">
          <span> ⸱ </span>
          <span>{{ status.enabled ? 'Enabled' : 'Disabled' }}</span>
        </template>
      </q-tooltip>
      <q-menu
        v-if="engine.auth.isOperator"
        v-model="menuIsOpen"
        anchor="top right"
        class="no-shadow"
        :offset="[8, 0]"
      >
        <q-list bordered class="rounded-corners" dense>
          <q-item clickable @click="status.running ? engine.stop(address) : engine.start(address)">
            <q-item-section>
              <q-item-label>{{ status.running ? 'Stop' : 'Start' }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            clickable
            @click="status.enabled ? engine.disable(address) : engine.enable(address)"
          >
            <q-item-section>
              <q-item-label>{{ status.enabled ? 'Disable' : 'Enable' }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-separator />
          <q-item clickable @click="engine.start(address.all())">
            <q-item-section>
              <q-item-label>Start All</q-item-label>
            </q-item-section>
          </q-item>
          <q-separator />
          <q-item clickable @click="engine.enable(address.all())">
            <q-item-section>
              <q-item-label>Enable All</q-item-label>
            </q-item-section>
          </q-item>
          <q-item clickable @click="engine.disable(address.all())">
            <q-item-section>
              <q-item-label>Disable All</q-item-label>
            </q-item-section>
          </q-item>
          <q-separator />
          <q-item :to="`/systems/${address}`">
            <q-item-section>
              <q-item-label>View</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </q-badge>
  </div>
</template>

<style lang="scss" module>
.root {
  background-color: black;
  outline: 4px dotted black;
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
</style>
