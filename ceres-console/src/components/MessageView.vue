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
        :connection-name="componentName"
        label="Send Command"
        :unit-name="unitName"
        @send="(command) => onSend(command)"
      />
    </div>
  </section-card>
</template>

<script lang="ts" setup>
import { getComponent, useMessageStream } from '@/api/queries'
import CommandInput from '@/components/CommandInput.vue'
import MessageViewItem from '@/components/MessageViewItem.vue'
import SectionCard from '@/components/SectionCard.vue'
import moment from 'moment'
import { QScrollArea } from 'quasar'
import { nextTick, onMounted } from 'vue'

const {
  title,
  containerClass = undefined,
  unitName,
  componentName,
} = defineProps<{
  title: string
  containerClass?: string | null
  unitName: string
  componentName: string
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

const info = await getComponent(unitName, componentName)

let search = $ref('')
let container = $shallowRef<QScrollArea | null>(null)
let messages = $ref<Message[]>([])

useMessageStream(info.id, (message) => {
  messages.push(message)
  setTimeout(() => {
    nextTick(() => {
      scrollToBottom()
    })
  })
})

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
