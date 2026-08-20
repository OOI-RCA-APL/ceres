<script lang="ts" setup>
import { connectionLabel } from '@/api/components'
import { useEngine } from '@/api/engine'
import type { Message } from '@/api/messages'
import type { DataContentDisplay } from '@/components/c-data-content.vue'

const { message, dataDisplay = 'default' } = defineProps<{
  message: Message
  dataDisplay?: DataContentDisplay
}>()

const engine = useEngine()

// Looked up by address as well as by name, a connection name being unique only within its own
// component while a pane scoped to a subtree draws messages from several.
const connection = $computed(() =>
  message.connection == null
    ? null
    : engine.components.getConnection(message.address, message.connection),
)

const directionColor = $computed(() => {
  switch (message.direction) {
    case 'receive':
      return 'info'
    case 'send':
      return 'warning'
  }
})
</script>

<template>
  <c-record-view-record :record="message">
    <c-record-view-cell class="w-0 min-w-20" name="connection">
      <!-- The name the filters match on stays reachable from the label that replaced it. -->
      <c-tooltip
        v-if="connection != null"
        :ui="{ content: 'h-auto flex-col items-start gap-0.5 py-1.5' }"
      >
        <span class="font-mono text-[10px] whitespace-nowrap">
          {{ connectionLabel(connection) }}
        </span>
        <template #content>
          <c-text variant="mono-sm">{{ connection.name }}</c-text>
          <c-text variant="description">{{ connection.uri }}</c-text>
        </template>
      </c-tooltip>
      <span v-else class="font-mono text-[10px] whitespace-nowrap">
        {{ message.connection ?? '' }}
      </span>
    </c-record-view-cell>
    <c-record-view-cell class="w-0 min-w-17" name="direction">
      <div class="justify-center">
        <c-badge
          :color="directionColor"
          :ui="{ base: 'font-mono text-[8px] px-1.5 py-0 min-w-9.5 justify-center rounded-full' }"
          variant="solid"
        >
          {{ message.direction }}
        </c-badge>
      </div>
    </c-record-view-cell>
    <c-record-view-cell name="data">
      <c-data-content
        class="font-mono text-[9px] whitespace-nowrap"
        :data="message.data"
        :display="dataDisplay"
      />
    </c-record-view-cell>
  </c-record-view-record>
</template>
