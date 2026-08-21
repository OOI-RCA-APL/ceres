<script lang="ts" setup>
import { upperFirst } from 'lodash-es'

import type { Address } from '@/api/address'
import type { ConnectionInfo, ConnectionStateInfo } from '@/api/components'
import type { Connectivity } from '@/api/shared'
import type { DetailWidgetAction } from '@/components/c-detail-widget-section.vue'
import { scopedQuery } from '@/filters/model'
import icons from '@/icons'
import { toTitle } from '@/utilities'
import { createWidget } from '@/workspace'
import type { MessagesWidget, ParticlesWidget, Widget, WidgetPlacement } from '@/workspace'

type Connection = ConnectionInfo | ConnectionStateInfo

const {
  address,
  connections,
  running = false,
  insertDrag = null,
  insertAt = null,
} = defineProps<{
  address: Address
  connections: Connection[]

  /** Whether the component is running, which decides how its connectivity reads. */
  running?: boolean

  insertDrag?:
    ((widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) => void) | null
  insertAt?: ((widgets: Widget[], placement: WidgetPlacement) => void) | null
}>()

const emit = defineEmits<{
  create: [widgets: Widget[]]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

/** One record view of this component narrowed to `names`, several connections joining as
alternatives to each other. */
function viewFor(kind: 'messages' | 'particles', names: string[]): Widget {
  const widget = createWidget(kind) as MessagesWidget | ParticlesWidget

  // A connection reads as either kind, so the name carries which one this is. Several
  // connections keep the default, no one of them standing for the rest.
  if (names.length === 1) {
    widget.name = `${toTitle(names[0] as string)} ${kind === 'messages' ? 'Messages' : 'Particles'}`
  }

  widget.query = scopedQuery(address.toString(), 'connection', names)
  return widget
}

function viewsFor(kind: 'messages' | 'particles', names: string[]): Widget[] {
  return names.map((name) => viewFor(kind, [name]))
}

const actions: DetailWidgetAction<Connection>[] = [
  {
    label: 'Create Messages View',
    separateLabel: 'Create Separate Messages Views',
    icon: icons.messages,
    combined: (chosen) => [viewFor('messages', chosen.map(nameOf))],
    separate: (chosen) => viewsFor('messages', chosen.map(nameOf)),
  },
  {
    label: 'Create Particles View',
    separateLabel: 'Create Separate Particles Views',
    icon: icons.particles,
    combined: (chosen) => [viewFor('particles', chosen.map(nameOf))],
    separate: (chosen) => viewsFor('particles', chosen.map(nameOf)),
  },
]

function nameOf(connection: Connection): string {
  return connection.name
}

const connectivityColors: Record<Connectivity, string> = {
  connected: 'bg-success',
  connecting: 'bg-warning',
  disconnected: 'bg-error',
}

// A stopped component's connections are expectedly down, shown inert grey rather than alarming
// red, with the pulse stilled to match.
function connectivityColor(connectivity: Connectivity): string {
  return running ? connectivityColors[connectivity] : 'bg-inverted/40'
}
</script>

<template>
  <c-detail-widget-section
    v-model:expanded="expanded"
    :actions
    empty="No connections."
    :insert-at
    :insert-drag
    :items="connections"
    :key-of="nameOf"
    title="Connections"
    @create="(widgets: Widget[]) => emit('create', widgets)"
  >
    <template #row="{ item }">
      <div class="grow">
        <div class="flex items-baseline gap-2">
          <c-text variant="body3">{{ item.name }}</c-text>
          <c-text v-if="item.label" variant="description">{{ item.label }}</c-text>
        </div>
        <c-text variant="description">{{ item.uri }}</c-text>
      </div>
      <c-tooltip v-if="'connectivity' in item" :text="upperFirst(item.connectivity)">
        <span
          :class="[$style.dot, !running && $style.still, connectivityColor(item.connectivity)]"
        />
      </c-tooltip>
    </template>
  </c-detail-widget-section>
</template>

<style module>
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

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
</style>
