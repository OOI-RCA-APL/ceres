<script lang="ts" setup>
import { Address } from '@/address'
import { Alert, ComponentInfo, LogEntry, Message } from '@/api/models'
import {
  getAlerts,
  getComponent,
  getLogEntries,
  getMessages,
  sendMessage,
  useAlertStream,
  useLogEntryStream,
  useMessageStream,
} from '@/api/operations'
import CommandInput from '@/components/CommandInput.vue'
import ItemViewAlert from '@/components/ItemViewAlert.vue'
import ItemViewLogEntry from '@/components/ItemViewLogEntry.vue'
import ItemViewMessage from '@/components/ItemViewMessage.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { QVirtualScroll, useQuasar } from 'quasar'
import { computed, nextTick, onMounted, watch, watchEffect } from 'vue'

type Item = Readonly<Alert | Message | LogEntry>

const {
  title = undefined,
  address,
  kind,
} = defineProps<{
  title?: string
  containerClass?: string | null
  address: Address
  kind: 'alert' | 'message' | 'log-entry'
}>()

const pattern = $computed(() => new Address(address.toString() + '+'))

const quasar = useQuasar()
const get = $computed(() => {
  switch (kind) {
    case 'message':
      return getMessages
    case 'alert':
      return getAlerts
    case 'log-entry':
      return getLogEntries
  }
})

const useStream = $computed(() => {
  switch (kind) {
    case 'message':
      return useMessageStream
    case 'alert':
      return useAlertStream
    case 'log-entry':
      return useLogEntryStream
  }
})

const info = (await getComponent(address)) as ComponentInfo
if (info == null) {
  throw new Error('Component not found')
}

const itemsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / itemHeight))
const itemHeight = 28
const itemLoadSize = $computed(() => Math.min(itemsVisible + 100, 1000))
const itemSliceSize = 250
const itemCullThreshold = $computed(() => itemsVisible + 250)
const itemCullCount = $computed(() => itemsVisible + 100)

let search = $ref('')
let scroll = $shallowRef<QVirtualScroll | null>(null)
const container = $computed(() => {
  if (scroll == null) {
    return null
  }

  return scroll.$el as HTMLDivElement
})

const isShowingAll = $computed(() => search.length === 0)

let items = $shallowRef<Item[]>([])

const earliestItemTimestamp = $computed(() => items[0]?.timestamp ?? null)

let isExhausted = $ref(false)
let isDoingInitialLoad = $ref(true)
let isLoadingPrevious = $ref(false)
let isLoadingCurrent = $ref(false)

let containerInfo = $ref({
  scrollHeight: 0,
  scrollWidth: 0,
  scrollTop: 0,
  scrollLeft: 0,
  clientHeight: 0,
  clientWidth: 0,
})

function updateContainerInfo() {
  if (container != null) {
    containerInfo.scrollHeight = container.scrollHeight
    containerInfo.scrollWidth = container.scrollWidth
    containerInfo.scrollTop = container.scrollTop
    containerInfo.scrollLeft = container.scrollLeft
    containerInfo.clientHeight = container.clientHeight
    containerInfo.clientWidth = container.clientWidth
  }
}

async function onScroll() {
  updateContainerInfo()

  if (!isNearTop()) {
    return
  }

  if (isExhausted || isDoingInitialLoad || isLoadingCurrent || isLoadingPrevious) {
    return
  }

  try {
    isLoadingPrevious = true
    await loadPrevious()
  } finally {
    isLoadingPrevious = false
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

  return containerInfo.scrollTop <= 20 * itemHeight
}

function isAtBottom() {
  if (container == null) {
    return true
  }

  return containerInfo.scrollTop + containerInfo.clientHeight >= containerInfo.scrollHeight - 2
}

const isAtBottomComputed = $computed(isAtBottom)

const isShowingVerticalScrollBar = $computed(() => {
  if (container == null) {
    return true
  }

  return containerInfo.scrollHeight > containerInfo.clientHeight
})

const isShowingHorizontalScrollBar = $computed(() => {
  if (container == null) {
    return true
  }

  return containerInfo.scrollWidth > containerInfo.clientWidth
})

async function delay(milliseconds = 0) {
  return await new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function prependItems(prepended: Item[]) {
  const scrollTop = containerInfo.scrollTop
  const height = prepended.length * itemHeight
  items = [...prepended.map(Object.freeze), ...items] as Item[]
  scroll?.refresh(-1)
  container?.scrollTo({
    top: scrollTop + height,
  })
  await delay()
  await nextTick()
}

async function appendItems(appended: Item[]) {
  const follow = isAtBottom()
  items = [...items, ...appended.map(Object.freeze)] as Item[]
  if (follow) {
    if (items.length > itemCullThreshold) {
      items = items.slice(items.length - itemCullCount, items.length)
      await forceScrollToBottom(250)
    } else {
      scroll?.refresh(items.length + 1)
    }
  }
  await delay()
  await nextTick()
}

async function loadPrevious() {
  const results: Item[] = await get({
    address: pattern,
    search: search === '' ? undefined : search,
    before: earliestItemTimestamp == null ? undefined : earliestItemTimestamp.format(),
    order: 'new-to-old',
    limit: itemLoadSize,
  })

  isExhausted = results.length === 0
  await prependItems(results.reverse())
}

async function loadCurrent() {
  const results: Item[] = await get({
    address: pattern,
    search: search === '' ? undefined : search,
    order: 'new-to-old',
    limit: itemLoadSize,
  })

  isExhausted = results.length === 0
  items = []
  await appendItems(results.reverse())
}

useStream(
  computed(() => ({
    address: pattern,
    search: search === '' ? undefined : search,
  })),
  async (item: Item) => {
    await appendItems([item])
  }
)

function scrollToBottom() {
  if (scroll != null) {
    scroll.scrollTo(items.length)
  }
}

async function forceScrollToBottom(duration = 500, interval = 50) {
  const id = setInterval(() => {
    scrollToBottom()
  }, interval)

  await delay(duration)
  clearInterval(id)
}

onMounted(async () => {
  try {
    try {
      isDoingInitialLoad = true
      isLoadingCurrent = true
      await loadCurrent()
    } finally {
      isLoadingCurrent = false
    }
  } finally {
    void delay(1000).then(() => {
      isDoingInitialLoad = false
    })
  }

  forceScrollToBottom()
})

watch([computed(() => search)], async () => {
  if (isDoingInitialLoad) {
    return
  }

  try {
    isLoadingCurrent = true
    await loadCurrent()
    forceScrollToBottom()
  } finally {
    isLoadingCurrent = false
  }
})

async function onSend(data: string) {
  const result = await sendMessage(address, data)
  if (result.ok) {
    return
  }

  quasar.notify({
    type: 'negative',
    message: `Message failed to send. ${JSON.stringify(result.error)}`,
  })
}
</script>

<template>
  <section-card :title="title">
    <template #header-append>
      <q-space class="gt-sm" />
      <div class="col-grow q-ml-sm self-search-input-container">
        <q-input
          v-model="search"
          class="item-view-search-input"
          :debounce="100"
          dense
          filled
          input-class="monospace-md"
        >
          <template #prepend>
            <q-icon name="search" size="20px" />
          </template>
        </q-input>
      </div>
    </template>
    <div v-if="items.length" class="col-grow self-virtual-scroll-container">
      <q-virtual-scroll
        ref="scroll"
        v-slot="{ item }"
        class="fit item-view-virtual-scroll self-virtual-scroll"
        dense
        flat
        :items="items"
        separator="cell"
        type="table"
        :virtual-scroll-item-size="itemHeight"
        :virtual-scroll-slice-size="itemSliceSize"
      >
        <item-view-message v-if="kind === 'message'" :key="(item as Message).id" :message="item" />
        <item-view-alert v-else-if="kind === 'alert'" :key="(item as Alert).id" :alert="item" />
        <item-view-log-entry v-else :key="(item as LogEntry).id" :entry="item" />
      </q-virtual-scroll>
      <transition appear enter-active-class="animated fadeIn" leave-active-class="animated fadeOut">
        <q-btn
          v-if="!isDoingInitialLoad && !isAtBottomComputed"
          class="absolute-bottom-right"
          color="primary"
          :icon="icons.arrowDownward"
          round
          size="sm"
          :style="{
            right: isShowingVerticalScrollBar ? '12px' : '4px',
            bottom: isShowingHorizontalScrollBar ? '12px' : '4px',
          }"
          @click="scrollToBottom"
        >
          <q-tooltip class="bg-primary text-white">Latest</q-tooltip>
        </q-btn>
      </transition>
    </div>
    <div v-else-if="!isDoingInitialLoad" class="col-grow items-center justify-center row">
      <span class="self-empty-message-text text-italic">
        <template v-if="isShowingAll">
          No {{ kind.replace('log-entry', 'log entrie') }}s were found.
        </template>
        <template v-else>
          No matching {{ kind.replace('log-entry', 'log entrie') }}s were found.
        </template>
      </span>
    </div>
    <q-space v-else />
    <div v-if="kind === 'message'">
      <q-separator />
      <command-input :address="address" @send="onSend" />
    </div>
  </section-card>
</template>

<style lang="scss" scoped>
.self-virtual-scroll-container {
  contain: size !important; // This is needed for horizontal scrolling to work.
  position: relative;
}

.self-virtual-scroll {
  overscroll-behavior: contain;
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
.item-view-search-input .q-field__control,
.item-view-search-input .q-field__marginal {
  height: 28px;
}

.item-view-search-input {
  left: 4px;
  position: absolute;
  top: -14px;
  width: 100%;
}

.item-view-virtual-scroll .q-virtual-scroll__content {
  contain: unset !important;
}
</style>
