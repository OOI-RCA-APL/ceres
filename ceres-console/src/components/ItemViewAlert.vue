<template>
  <div class="row self-item-view-alert-root">
    <div class="self-timestamp">
      {{ moment.utc(alert.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS') }}
    </div>
    <q-chip class="self-level-chip" :color="levelColor" dense text-color="black">
      <span class="self-level-text">
        {{ alert.level }}
      </span>
    </q-chip>
    <div class="self-code">{{ alert.code }}</div>
    <div class="self-info">{{ JSON.stringify(alert.info, null, 2) }}</div>
  </div>
</template>

<script lang="ts" setup>
import { Alert } from '@/api/models'
import moment from 'moment'

const { alert } = defineProps<{
  alert: Alert
}>()

const levelColor = $computed(() => {
  switch (alert.level) {
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

<style lang="scss" scoped>
.self-item-view-alert-root {
  align-items: center;
  flex-wrap: nowrap;
  justify-items: center;
  min-height: 21.5px;
  white-space: nowrap;
}

.self-timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
  margin-right: 8px;
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

.self-code {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
  margin-right: 8px;
}

.self-info {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
}
</style>
