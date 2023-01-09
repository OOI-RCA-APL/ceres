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
        v-for="message in messages"
        :key="message.id"
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
import { ComponentInfo, Message } from '@/api/models'
import { getComponent, getMessages, useMessageStream } from '@/api/queries'
import CommandInput from '@/components/CommandInput.vue'
import MessageViewItem from '@/components/MessageViewItem.vue'
import SectionCard from '@/components/SectionCard.vue'
import { QScrollArea } from 'quasar'
import { computed, nextTick, onMounted, watch } from 'vue'

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

const info = (await getComponent(unitName, componentName)) as ComponentInfo
if (info == null) {
  throw new Error('Component not found')
}

let search = $ref('')
let container = $shallowRef<QScrollArea | null>(null)
let messages = $ref<Message[]>([])

const earliestMessageTimestamp = $computed(() => messages[0]?.timestamp ?? null)

let isExhausted = $ref(false)
let isDoingInitialLoad = $ref(true)
let isLoadingPreviousMessages = $ref(false)
let isLoadingCurrentMessages = $ref(false)

type ScrollInfo = {
  verticalPosition: number
  verticalPercentage: number
  verticalSize: number
  verticalContainerSize: number
}

let currentScroll: ScrollInfo | null = $ref(null)

async function onScroll(scroll: ScrollInfo) {
  currentScroll = scroll

  if (!isNearTop) {
    return
  }

  if (
    isExhausted ||
    isDoingInitialLoad ||
    isLoadingCurrentMessages ||
    isLoadingPreviousMessages ||
    !isNearTop
  ) {
    return
  }

  try {
    isLoadingPreviousMessages = true
    await loadPreviousMessages()
  } finally {
    isLoadingPreviousMessages = false
  }
}

const isNearTop = $computed(() => {
  if (currentScroll == null) {
    return false
  }

  return currentScroll.verticalPercentage < 0.2
})

const isAtBottom = $computed(() => {
  if (currentScroll == null) {
    return true
  }

  return currentScroll.verticalPercentage >= 0.995
})

async function delay(milliseconds = 0) {
  return await new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function prependMessages(prepended: Message[]) {
  const previousScrollHeight = currentScroll?.verticalSize
  const previousScrollPosition = currentScroll?.verticalPosition

  messages = [...prepended, ...messages]

  await delay(15)
  await nextTick()
  if (container == null || previousScrollHeight == null || previousScrollPosition == null) {
    return
  }

  const diff = container.getScroll().verticalSize - previousScrollHeight
  container.setScrollPosition('vertical', previousScrollPosition + diff)
  await delay()
  await nextTick()
}

async function appendMessages(appended: Message[]) {
  const isSticky = isAtBottom
  messages = [...messages, ...appended]

  await delay()
  await nextTick()

  if (isSticky) {
    scrollToBottom()
  }
}

async function loadPreviousMessages() {
  const results = await getMessages({
    component_id: info.id,
    search,
    before: earliestMessageTimestamp == null ? undefined : earliestMessageTimestamp,
    limit: 100,
  })

  isExhausted = results.length === 0
  await prependMessages(results)
}

async function loadCurrentMessages() {
  const results = await getMessages({
    component_id: info.id,
    search,
    limit: 100,
  })

  isExhausted = results.length === 0
  messages = []
  await appendMessages(results)
  scrollToBottom()
  await delay(15)
  await nextTick()
  scrollToBottom()
  console.log(results)
}

useMessageStream({ component_id: info.id, search }, async (message: Message) => {
  if (search == null || message.content.includes(search)) {
    messages.push(message)
  }

  if (isAtBottom) {
    await delay()
    await nextTick()
    scrollToBottom()
  }
})

function scrollToBottom() {
  if (container != null) {
    container.setScrollPosition('vertical', container.getScroll().verticalSize)
  }
}

async function onSend(command: string) {
  console.log('sending: ' + command)
  await delay()
  await nextTick()
  scrollToBottom()
}

try {
  try {
    isDoingInitialLoad = true
    isLoadingCurrentMessages = true
    await loadCurrentMessages()
  } finally {
    isLoadingCurrentMessages = false
  }
} finally {
  void delay(1000).then(() => {
    isDoingInitialLoad = false
  })
}

watch([computed(() => search)], async () => {
  if (isDoingInitialLoad) {
    return
  }

  try {
    isLoadingCurrentMessages = true
    await loadCurrentMessages()
  } finally {
    isLoadingCurrentMessages = false
  }
})

onMounted(async () => {
  const interval = setInterval(() => {
    scrollToBottom()
  }, 100)

  await delay(1000)
  clearInterval(interval)
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
  padding-top: 4px;
}

.self-message:last-child {
  padding-bottom: 4px;
}
</style>

<style lang="scss">
.message-view-search-input .q-field__control,
.message-view-search-input .q-field__marginal {
  height: 28px;
}

.message-view-search-input {
  left: 12px;
  position: absolute;
  top: -14px;
  width: 100%;
}
</style>
