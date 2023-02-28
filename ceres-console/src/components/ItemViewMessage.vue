<template>
  <div class="row self-item-view-message-root">
    <span class="self-timestamp">
      {{ moment.utc(message.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS') }}
    </span>
    <q-chip class="self-direction-chip" :color="directionColor" dense>
      <span class="self-direction-text">
        {{ message.direction }}
      </span>
    </q-chip>
    <span class="self-content">
      {{ message.content }}
    </span>
  </div>
</template>

<script lang="ts" setup>
import { Message } from '@/api/models'
import moment from 'moment'

const { message } = defineProps<{
  message: Message
}>()

const directionColor = $computed(() => {
  switch (message.direction) {
    case 'receive':
      return 'info'
    case 'send':
      return 'warning'
  }
})
</script>

<style lang="scss" scoped>
.self-item-view-message-root {
  align-items: center;
  flex-wrap: nowrap;
  justify-items: center;
  min-height: 21.5px;
  white-space: nowrap;
}

.self-direction-chip {
  font-size: 9px;
  margin-right: 8px;
  min-width: 50px;
  text-transform: uppercase;
  white-space: nowrap;
}

.self-direction-text {
  color: black;
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  white-space: nowrap;
  width: 100%;
}

.self-timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  margin-right: 4px;
  white-space: nowrap;
}

.self-content {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
}
</style>
