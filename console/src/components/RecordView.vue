<script lang="ts" setup>
import { Address } from '@/api/address'
import { Alert } from '@/api/alerts'
import { useEngine } from '@/api/engine'
import { LogEntry } from '@/api/log-entries'
import { Message } from '@/api/messages'
import { Item } from '@/api/shared'
import CommandInput from '@/components/CommandInput.vue'
import RecordViewAlert from '@/components/RecordViewAlert.vue'
import RecordViewLogEntry from '@/components/RecordViewLogEntry.vue'
import RecordViewMessage from '@/components/RecordViewMessage.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { useNotify } from '@/notify'
import { debouncedComputed } from '@/utilities'
import { useWindowFocus } from '@vueuse/core'
import _ from 'lodash'
import moment, { Moment } from 'moment'
import { QVirtualScroll, debounce } from 'quasar'
import { computed, nextTick, onMounted, reactive, watch, watchEffect } from 'vue'

const {
  title = undefined,
  address,
  type,
  showCommandInput = false,
} = defineProps<{
  title?: string
  containerClass?: string | null
  address: Address
  type: 'alert' | 'message' | 'log-entry'
  showCommandInput?: boolean
}>()

const selector = $computed(() => new Address(address.toString() + ':all'))

const engine = useEngine()
const notify = useNotify()

const get = $computed(() => {
  switch (type) {
    case 'message':
      return engine.messages.getAll
    case 'alert':
      return engine.alerts.getAll
    case 'log-entry':
      return engine.logs.getAll
  }
})

const useStream = $computed(() => {
  switch (type) {
    case 'message':
      return engine.messages.useStream
    case 'alert':
      return engine.alerts.useStream
    case 'log-entry':
      return engine.logs.useStream
  }
})

const info = engine.components.get(address)
if (info == null) {
  throw new Error('Component not found')
}

const itemsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / itemHeight))
const itemHeight = 24
const itemLoadSizeInitial = $computed(() => Math.min(itemsVisible + 40, 1000))
const itemLoadSize = $computed(() => Math.min(itemsVisible + 25, 1000))
const itemSliceSize = 250
const itemCullThreshold = $computed(() => itemsVisible + 500)
const itemCullCount = $computed(() => itemsVisible + 100)
const itemsUntilNearTop = 30

const possibleSearchFields = $computed(() => {
  const shared = ['timestamp', 'address']
  switch (type) {
    case 'message':
      return [...shared, 'direction', 'content']
    case 'alert':
      return [...shared, 'code']
    case 'log-entry':
      return [...shared, 'content']
  }
})

const defaultSearchField = $computed(() => {
  switch (type) {
    case 'message':
      return 'content'
    case 'alert':
      return 'code'
    case 'log-entry':
      return 'content'
  }
})

const searchFilter = reactive({ search: '', field: defaultSearchField as string })
let searchFilterKey = $ref(0)
watch(searchFilter, () => {
  searchFilterKey++
})

let scroll = $shallowRef<QVirtualScroll | null>(null)
const container = $computed(() => {
  if (scroll == null) {
    return null
  }

  return scroll.$el as HTMLDivElement
})

let items = $shallowRef<Item[]>([])
let itemsStreamed = $shallowRef<Item[]>([])
let lastLoadedCurrent = $shallowRef<Moment | null>(null)

const earliestItemTimestamp = $computed(() => items[0]?.timestamp ?? null)

const isWindowFocused = $(useWindowFocus())
const isShowingAll = $computed(
  () => searchFilter.search == null || searchFilter.search.length === 0
)

let isExhausted = $ref(false)
let isLoadingPrevious = $ref(false)
let isLoadingCurrent = $ref(true)

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

  if (isExhausted || isLoadingCurrent || isLoadingPrevious || !isWindowFocused) {
    return
  }

  if (lastLoadedCurrent == null || moment.utc().diff(lastLoadedCurrent) < 1000) {
    return
  }

  if (!isNearTop()) {
    return
  }

  isLoadingPrevious = true
  await loadPrevious()
}

watchEffect((onCleanup) => {
  const element = container
  element?.addEventListener('scroll', onScroll, { passive: true })
  void onScroll()
  onCleanup(() => {
    element?.removeEventListener('scroll', onScroll)
  })
})

function isNearTop() {
  if (container == null) {
    return false
  }

  return containerInfo.scrollTop <= itemsUntilNearTop * itemHeight
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
  items = [...prepended, ...items] as Item[]
  scroll?.refresh(-1)
  await nextTick()
  container?.scrollTo({
    top: scrollTop + height,
  })
  await nextTick()
}

async function appendItems(appended: Item[]) {
  const follow = isAtBottom()
  let resort = false
  if (appended.length > 0 && items.length > 0) {
    if (appended[appended.length - 1].timestamp < items[items.length - 1].timestamp) {
      resort = true
    }
  }

  let buffer = [...items, ...appended] as Item[]
  if (resort) {
    buffer = _.sortBy(buffer, (item) => item.timestamp)
  }

  items = buffer

  if (follow) {
    if (items.length > itemCullThreshold) {
      items = items.slice(items.length - itemCullCount, items.length)
      await forceScrollToBottom(100)
    } else {
      scroll?.refresh(items.length + 1)
    }
  }

  await nextTick()
}

async function loadPrevious() {
  isLoadingPrevious = true

  const key = searchFilterKey
  try {
    const results: Item[] = await get({
      address: selector,
      search: searchFilter.search === '' ? undefined : searchFilter.search,
      search_field: searchFilter.field,
      before: earliestItemTimestamp == null ? undefined : earliestItemTimestamp,
      order: '-timestamp',
      limit: itemLoadSize,
    })

    if (key !== searchFilterKey) {
      return
    }

    isExhausted = results.length === 0
    await prependItems(results.reverse())
  } finally {
    isLoadingPrevious = false
  }
}

async function loadCurrent() {
  updateContainerInfo()

  isLoadingCurrent = true
  items = []
  itemsStreamed = []

  const key = searchFilterKey
  try {
    const results: Item[] = await get({
      address: selector,
      search: searchFilter.search === '' ? undefined : searchFilter.search,
      search_field: searchFilter.field,
      order: '-timestamp',
      limit: itemLoadSizeInitial,
    })

    if (key !== searchFilterKey) {
      return
    }

    isExhausted = results.length === 0
    const appended = [...results.reverse(), ...itemsStreamed]
    await appendItems(appended)
    lastLoadedCurrent = moment.utc()
    await forceScrollToBottom()
    updateContainerInfo()
  } finally {
    isLoadingCurrent = false
  }
}

function scrollToBottom() {
  if (scroll != null) {
    scroll.scrollTo(items.length)
  }
}

async function onScrollToBottomClicked() {
  items = items.slice(items.length - itemCullCount, items.length)
  await nextTick()
  await forceScrollToBottom(250)
}

async function forceScrollToBottom(duration = 500, interval = 50) {
  scrollToBottom()
  const id = setInterval(() => {
    scrollToBottom()
  }, interval)

  await delay(duration)
  clearInterval(id)
}

onMounted(async () => {
  await loadCurrent()
})

const debouncedLoadCurrent = debounce(loadCurrent, 750)

watch($$(searchFilterKey), async () => {
  items = []
  itemsStreamed = []
  isLoadingCurrent = true
  debouncedLoadCurrent()
})

const debouncedFilter = debouncedComputed(() => _.cloneDeep(searchFilter), 750)

useStream(
  computed(() => ({
    address: selector,
    search: debouncedFilter.value.search === '' ? undefined : debouncedFilter.value.search,
  })),
  async (item: Item) => {
    if (isLoadingCurrent) {
      itemsStreamed = [...itemsStreamed, item]
    } else {
      await appendItems([item])
    }
  }
)

async function onSend(data: string) {
  const result = await engine.messages.send(address, data)
  if (result.ok) {
    return
  }

  notify.error(`Message failed to send. ${JSON.stringify(result.error)}`)
}
</script>

<template>
  <section-card :title>
    <template #header-append>
      <q-space class="gt-sm" />
      <div :class="[$style.searchInputContainer, 'col-grow q-ml-sm']">
        <q-input
          v-model="searchFilter.search"
          :class="$style.searchInput"
          dense
          input-class="monospace-sm"
          outlined
          placeholder="Search"
          spellcheck="false"
        >
          <template #prepend>
            <q-icon name="search" size="20px" />
          </template>
          <template #append>
            <q-badge clickable>
              {{ searchFilter.field }}
              <q-menu anchor="bottom right" class="no-shadow" :offset="[0, 5]" self="top right">
                <q-list bordered dense separator>
                  <q-item
                    v-for="field in possibleSearchFields"
                    :key="field"
                    :active="searchFilter.field === field"
                    :class="$style.menuItem"
                    clickable
                    dense
                    @click="searchFilter.field = field"
                  >
                    {{ field }}
                  </q-item>
                </q-list>
              </q-menu>
            </q-badge>
          </template>
        </q-input>
      </div>
    </template>
    <div :class="[$style.virtualScrollContainer, 'col-grow']">
      <transition-group
        appear
        enter-active-class="animated fadeIn fast"
        leave-active-class="animated fadeOut fast"
      >
        <div
          v-if="isLoadingCurrent"
          key="spinner"
          class="absolute-center items-center justify-center row"
        >
          <q-spinner-orbit color="primary" size="24px" />
        </div>
        <span v-else-if="items.length === 0" key="empty" class="absolute-center">
          <span :class="[$style.emptyMessageText, 'text-italic']">
            <template v-if="isShowingAll">
              No {{ type.replace('log-entry', 'log entrie') }}s were found.
            </template>
            <template v-else>
              No matching {{ type.replace('log-entry', 'log entrie') }}s were found.
            </template>
          </span>
        </span>
      </transition-group>
      <q-virtual-scroll
        ref="scroll"
        v-slot="{ item }"
        :class="['fit', $style.virtualScroll, items.length === 0 && $style.virtualScrollEmpty]"
        dense
        flat
        :items
        separator="cell"
        square
        type="table"
        :virtual-scroll-item-size="itemHeight"
        :virtual-scroll-slice-size="itemSliceSize"
      >
        <record-view-message
          v-if="type === 'message'"
          :key="(item as Message).id"
          :message="item"
        />
        <record-view-alert v-else-if="type === 'alert'" :key="(item as Alert).id" :alert="item" />
        <record-view-log-entry v-else :key="(item as LogEntry).id" :entry="item" />
      </q-virtual-scroll>
      <transition appear enter-active-class="animated fadeIn" leave-active-class="animated fadeOut">
        <q-btn
          v-if="!isLoadingCurrent && !isAtBottomComputed"
          class="absolute-bottom-right"
          color="primary"
          :icon="icons.arrowDown"
          round
          size="sm"
          :style="{
            right: isShowingVerticalScrollBar ? '20px' : '4px',
            bottom: isShowingHorizontalScrollBar ? '20px' : '4px',
          }"
          @click="onScrollToBottomClicked"
        >
          <q-tooltip class="bg-primary text-white">Latest</q-tooltip>
        </q-btn>
      </transition>
    </div>
    <div v-if="type === 'message' && showCommandInput">
      <q-separator />
      <command-input :address @send="onSend" />
    </div>
  </section-card>
</template>

<style lang="scss" module>
.virtualScrollContainer {
  contain: size !important; // This is needed for horizontal scrolling to work.
  position: relative;
}

.virtualScroll {
  overscroll-behavior: contain;
  opacity: 1;
  transition: opacity 0.25s ease-out;
}

.virtualScrollEmpty {
  opacity: 0;
}

.searchInputContainer {
  min-width: 60px !important;
  position: relative;
}

@media (min-width: $breakpoint-md-min) {
  .searchInputContainer {
    max-width: 280px !important;
  }
}

.emptyMessageText {
  font-size: 13px;
  opacity: 0.5;
}

.searchInput :global(.q-field__control),
.searchInput :global(.q-field__marginal) {
  height: 28px;
}

.searchInput {
  left: 4px;
  position: absolute;
  top: -14px;
  width: 100%;
  opacity: 0.75;
}

.searchInput:focus-within,
.searchInput:hover {
  opacity: 1;
}

.virtualScroll :global(.q-virtual-scroll__content) {
  contain: unset !important;
}

.menuItem {
  min-height: unset !important;
  font-size: 13px;
}
</style>
