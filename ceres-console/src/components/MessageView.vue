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
    <q-virtual-scroll
      v-if="messages.length"
      ref="scroll"
      v-slot="{ item: message }"
      class="col-grow message-view-message-container self-message-container"
      :items="messages"
      :virtual-scroll-item-size="messageHeight"
      :virtual-scroll-slice-size="250"
    >
      <message-view-item :key="message.id" :message="message" />
    </q-virtual-scroll>
    <div v-else-if="!isDoingInitialLoad" class="col-grow items-center justify-center row">
      <span class="self-empty-message-text text-italic">
        <template v-if="isShowingAll">No messages were found.</template>
        <template v-else>No matching messages were found.</template>
      </span>
    </div>
  </section-card>
</template>

<script lang="ts" setup>
import { ComponentInfo, Message } from '@/api/models'
import { getComponent, getMessages, useMessageStream } from '@/api/queries'
import MessageViewItem from '@/components/MessageViewItem.vue'
import SectionCard from '@/components/SectionCard.vue'
import { QVirtualScroll } from 'quasar'
import { computed, nextTick, onMounted, watch, watchEffect } from 'vue'

const { title, unitName, componentName } = defineProps<{
  title: string
  containerClass?: string | null
  unitName: string
  componentName: string
}>()

const info = (await getComponent(unitName, componentName)) as ComponentInfo
if (info == null) {
  throw new Error('Component not found')
}

const messageHeight = 21.5

let search = $ref('')
let scroll = $shallowRef<QVirtualScroll | null>(null)
const container = $computed(() => {
  if (scroll == null) {
    return null
  }

  return scroll.$el as HTMLDivElement
})

const isShowingAll = $computed(() => search.length === 0)

let messages = $ref<Message[]>([])

const earliestMessageTimestamp = $computed(() => messages[0]?.timestamp ?? null)

let isExhausted = $ref(false)
let isDoingInitialLoad = $ref(true)
let isLoadingPreviousMessages = $ref(false)
let isLoadingCurrentMessages = $ref(false)

let containerInfo = $ref({
  scrollHeight: 0,
  scrollTop: 0,
  clientHeight: 0,
})

function updateContainerInfo() {
  if (container != null) {
    containerInfo.scrollHeight = container.scrollHeight
    containerInfo.scrollTop = container.scrollTop
    containerInfo.clientHeight = container.clientHeight
  }
}

async function onScroll() {
  updateContainerInfo()

  if (!isNearTop()) {
    return
  }

  if (isExhausted || isDoingInitialLoad || isLoadingCurrentMessages || isLoadingPreviousMessages) {
    return
  }

  try {
    isLoadingPreviousMessages = true
    await loadPreviousMessages()
  } finally {
    isLoadingPreviousMessages = false
  }
}

watchEffect((onCleanup) => {
  const element = container
  element?.addEventListener('scroll', onScroll)
  void onScroll()
  onCleanup(() => {
    element?.removeEventListener('scroll', onScroll)
  })
})

function isNearTop() {
  if (container == null) {
    return false
  }

  return containerInfo.scrollTop < 20 * messageHeight
}

function isAtBottom() {
  if (container == null) {
    return true
  }

  return containerInfo.scrollTop + containerInfo.clientHeight >= containerInfo.scrollHeight - 2
}

async function delay(milliseconds = 0) {
  return await new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function prependMessages(prepended: Message[]) {
  messages = Object.freeze([...prepended, ...messages]) as Message[]
  scroll?.refresh(prepended.length)

  await delay(15)
  await nextTick()
  await delay()
  await nextTick()
}

async function appendMessages(appended: Message[]) {
  const follow = isAtBottom()
  messages = Object.freeze([...messages, ...appended]) as Message[]
  if (follow) {
    scroll?.refresh(messages.length)
  }

  await delay(50)
  await nextTick()
  await delay()
  await nextTick()

  if (follow) {
    scroll?.scrollTo(messages.length, 'end-force')
  }
}

async function loadPreviousMessages() {
  const results = await getMessages({
    source: info.address,
    search: search === '' ? undefined : search,
    before: earliestMessageTimestamp == null ? undefined : earliestMessageTimestamp,
    order: 'new-to-old',
    limit: 100,
  })

  isExhausted = results.length === 0
  await prependMessages(results.reverse())
}

async function loadCurrentMessages() {
  const results = await getMessages({
    source: info.address,
    search: search === '' ? undefined : search,
    order: 'new-to-old',
    limit: 100,
  })

  isExhausted = results.length === 0
  messages = []
  await appendMessages(results.reverse())
}

useMessageStream(
  computed(() => ({
    source: info.address,
    search: search === '' ? undefined : search,
  })),
  async (message: Message) => {
    await appendMessages([message])
  }
)

function scrollToBottom() {
  if (scroll != null) {
    scroll.scrollTo(messages.length)
  }
}

onMounted(async () => {
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
  const interval = setInterval(() => {
    scrollToBottom()
  }, 100)

  await delay(1000)
  clearInterval(interval)
})

watch([computed(() => search)], async () => {
  if (isDoingInitialLoad) {
    return
  }

  try {
    isLoadingCurrentMessages = true
    await loadCurrentMessages()
    scrollToBottom()
  } finally {
    isLoadingCurrentMessages = false
  }
})
</script>

<style lang="scss" scoped>
.self-message-container {
  height: 0; // Set so flex-box sizing works correctly.
  overscroll-behavior: contain;
  padding: 0 8px;
}

.self-search-input-container {
  min-width: 60px;
  position: relative;
}

@media (min-width: $breakpoint-md-min) {
  .self-search-input-container {
    max-width: 280px;
  }
}

.self-empty-message-text {
  font-size: 13px;
  opacity: 0.5;
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

.message-view-message-container .q-virtual-scroll__content {
  contain: none !important;
}
</style>
