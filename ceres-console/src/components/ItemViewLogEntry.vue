<script lang="ts" setup>
import { LogEntry } from '@/api/models'

const { entry } = defineProps<{
  entry: LogEntry
}>()

const levelColor = $computed(() => {
  switch (entry.level) {
    case 'debug':
      return 'grey'
    case 'info':
      return 'info'
    case 'warning':
      return 'warning'
    case 'error':
      return 'negative'
    case 'critical':
      return 'negative'
  }
})
</script>

<template>
  <div class="row self-item-view-log-entry-root">
    <span class="self-timestamp">
      {{ entry.timestamp.format('YYYY-MM-DD HH:mm:ss.SSS') }}
    </span>
    <q-chip class="self-level-chip" :color="levelColor" dense text-color="black">
      <span class="self-level-text">
        {{ entry.level }}
      </span>
    </q-chip>
    <span class="self-content">
      {{ JSON.stringify(entry.content) }}
    </span>
  </div>
</template>

<style lang="scss" scoped>
.self-item-view-log-entry-root {
  align-items: center;
  flex-wrap: nowrap;
  justify-items: center;
  min-height: 21.5px;
  white-space: nowrap;
}

.self-timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  margin-right: 4px;
  white-space: nowrap;
}

.self-level-chip {
  font-size: 9px;
  margin-right: 8px;
  min-width: 58px;
  text-transform: uppercase;
  white-space: nowrap;
}

.self-level-text {
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  white-space: nowrap;
  width: 100%;
}

.self-content {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
}
</style>
