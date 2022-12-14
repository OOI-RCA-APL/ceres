<template>
  <div class="row self-root">
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
import moment from 'moment'

type Message = {
  timestamp: string
  direction: 'send' | 'receive'
  content: string
}

const { message } = defineProps<{
  message: Message
}>()

const directionColor = $computed(() => {
  if (message.direction === 'receive') {
    return 'info'
  }

  if (message.direction === 'send') {
    return 'warning'
  }

  return 'primary'
})
</script>

<style lang="scss" scoped>
.self-root {
  align-items: center;
  flex-wrap: nowrap;
  justify-items: center;
  padding-left: 8px;
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
