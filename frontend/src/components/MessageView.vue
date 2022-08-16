<template>
  <section-card :title="title">
    <template #header-append>
      <q-space class="gt-sm" />
      <div class="col-grow q-ml-sm self-search-input-container">
        <q-input v-model="search" class="message-view-search-input" :debounce="50" dense outlined>
          <template #prepend>
            <q-icon name="search" />
          </template>
        </q-input>
      </div>
    </template>
    <q-scroll-area ref="container" :class="containerClass" @scroll="onScroll">
      <message-view-item
        v-for="(message, i) in matched"
        :key="i"
        class="self-message"
        :message="message"
      />
    </q-scroll-area>
    <q-separator class="q-mb-sm" />
    <div class="q-px-sm">
      <command-input
        :connection-name="connectionName"
        label="Send Command"
        :unit-name="unitName"
        @send="(command) => onSend(command)"
      />
    </div>
  </section-card>
</template>

<script lang="ts" setup>
import MessageViewItem from '@/components/MessageViewItem.vue'
import SectionCard from '@/components/SectionCard.vue'
import moment from 'moment'
import { QScrollArea } from 'quasar'
import { onMounted, nextTick } from 'vue'
import CommandInput from '@/components/CommandInput.vue'

const { title, containerClass = undefined } = defineProps<{
  title: string
  containerClass?: string | null
  unitName: string
  connectionName: string
}>()

type Message = {
  timestamp: string
  direction: 'send' | 'receive'
  content: string
}

type ScrollInfo = {
  verticalPosition: number
  verticalPercentage: number
  verticalSize: number
  verticalContainerSize: number
}

function generateMessages() {
  const output: Message[] = []

  for (let i = 0; i < 100; i++) {
    const timestamp = moment
      .utc()
      .subtract(1, 'day')
      .subtract(60, 'seconds')
      .add(Math.random() * 60, 'seconds')

    if (Math.random() < 0.9) {
      output.push({
        timestamp: timestamp.format(),
        direction: 'receive',
        content: String(Math.floor(Math.random() * 10000)),
      })
    } else {
      output.push({
        timestamp: timestamp.format(),
        direction: 'send',
        content: '<SETTIME:' + timestamp.format(),
      })
    }
  }

  return output
}

let search = $ref('')
let container = $ref<QScrollArea | null>(null)
let messages = $ref<Message[]>(generateMessages())

let scrollInfo = $ref(null as ScrollInfo | null)

const matched = $computed(() =>
  messages.filter(
    (message) =>
      message.content.toLowerCase().includes(search.toLowerCase()) ||
      message.direction.toLowerCase().includes(search.toLowerCase()) ||
      moment.utc(message.timestamp).format('YYYY/MM/DD HH:mm:ss.SSS').includes(search.toLowerCase())
  )
)

function onScroll(info: ScrollInfo) {
  scrollInfo = info
}

function scrollToBottom() {
  if (container != null && scrollInfo != null) {
    container.setScrollPosition('vertical', container.getScroll().verticalSize)
  }
}

function onSend(command: string) {
  messages.push({
    timestamp: moment.utc().format(),
    direction: 'send',
    content: command,
  })

  setTimeout(() => {
    nextTick(() => {
      scrollToBottom()
    })
  })
}

onMounted(() => {
  const interval = setInterval(() => {
    scrollToBottom()
  }, 100)

  setTimeout(() => {
    clearInterval(interval)
  }, 1000)
})
</script>

<style lang="scss" scoped>
.self-search-input-container {
  min-width: 60px;
  position: relative;
}

@media (min-width: $breakpoint-md-min) {
  .self-search-input-container {
    max-width: 280px;
  }
}

.self-message:first-child {
  padding-top: 8px;
}

.self-message:last-child {
  padding-bottom: 8px;
}
</style>

<style lang="scss">
.message-view-search-input .q-field__control,
.message-view-search-input .q-field__marginal {
  height: 28px;
}

.message-view-search-input {
  left: 0;
  position: absolute;
  top: -12px;
  width: 100%;
}
</style>
