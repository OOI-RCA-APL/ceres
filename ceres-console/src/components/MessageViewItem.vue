<template>
  <div class="items-center no-wrap q-px-md row">
    <span class="justify-center q-mr-sm self-timestamp text-no-wrap" style="display: inline-block">
      {{ moment.utc(message.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS') }}
    </span>
    <span class="justify-center q-mr-sm" style="display: inline-block">
      <q-chip class="self-direction" :color="directionColor" dense style="display: inline-block">
        <span class="full-width justify-center row text-black text-no-wrap">
          {{ message.direction.toUpperCase() }}
        </span>
      </q-chip>
    </span>
    <span class="self-content text-no-wrap" style="display: inline-block">
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
.self-direction {
  min-width: 50px;
  font-size: 9px;
}

.self-timestamp {
  font-size: 11px;
  font-family: 'Roboto Mono', monospace;
}

.self-content {
  font-size: 11px;
  font-family: 'Roboto Mono', monospace;
}
</style>
