<template>
  <div class="items-center no-wrap q-px-md row">
    <div class="justify-center q-mr-sm self-timestamp text-no-wrap">
      {{ moment.utc(message.timestamp).format('YYYY/MM/DD HH:mm:ss.SSS') }}
    </div>
    <div class="justify-center q-mr-sm">
      <q-chip class="self-direction" :color="directionColor" dense>
        <span class="full-width justify-center row text-no-wrap">
          {{ message.direction.toUpperCase() }}
        </span>
      </q-chip>
    </div>
    <div class="self-content text-no-wrap">
      {{ message.content }}
    </div>
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
.self-direction {
  min-width: 60px;
  padding: none;
  font-size: 11px;
}

.self-timestamp {
  font-size: 13px;
  font-family: 'Roboto Mono', monospace;
}

.self-content {
  font-size: 13px;
  font-family: 'Roboto Mono', monospace;
}
</style>
