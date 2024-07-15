<script lang="ts" setup>
import { Address } from '@/api/address'
import { Alert } from '@/api/alerts'
import { useEngine } from '@/api/engine'
import { LogEntry } from '@/api/log-entries'
import { Message } from '@/api/messages'
import { Record } from '@/api/shared'
import CommandInput from '@/components/CommandInput.vue'
import RecordViewAlert from '@/components/RecordViewAlert.vue'
import RecordViewLogEntry from '@/components/RecordViewLogEntry.vue'
import RecordViewMessage from '@/components/RecordViewMessage.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { provideRecordViewContext } from '@/record-view'
import { debouncedComputed } from '@/utilities'
import { useWindowFocus } from '@vueuse/core'
import _ from 'lodash'
import moment, { Moment } from 'moment'
import { debounce, QVirtualScroll } from 'quasar'
import { computed, nextTick, onMounted, reactive, VNodeRef, watch, watchEffect } from 'vue'

const {
  title = undefined,
  address: passedAddress,
  type,
  showCommandInput = false,
} = defineProps<{
  title?: string
  containerClass?: string | null
  address?: Address | null
  type: 'alert' | 'message' | 'log-entry'
  showCommandInput?: boolean
}>()

const selectedAddress = $ref(passedAddress ?? null)
const selector = $computed(() =>
  selectedAddress == null ? new Address('all') : new Address(selectedAddress.toString() + ':all')
)

const engine = useEngine()
// const notify = useNotify()

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

const context = provideRecordViewContext()

const recordsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / recordHeight))
const recordHeight = 24
const recordLoadSizeInitial = $computed(() => Math.min(recordsVisible + 40, 1000))
const recordLoadSize = $computed(() => Math.min(recordsVisible + 25, 1000))
const recordSliceSize = 250
const recordCullThreshold = $computed(() => recordsVisible + 500)
const recordCullCount = $computed(() => recordsVisible + 100)
const recordsUntilNearTop = 30

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
const scrollElement = $computed(() => {
  if (scroll == null) {
    return null
  }

  return scroll.$el as HTMLDivElement
})

let tableElement = $ref<HTMLElement | null>(null)
watchEffect(() => {
  if (tableElement == null) {
    return
  }

  // Sync the scroll position of the header with the main table.
  tableElement.scrollLeft = containerInfo.scrollLeft
})

let records = $shallowRef<Record[]>([])
let recordsStreamed = $shallowRef<Record[]>([])
let lastLoadedCurrent = $shallowRef<Moment | null>(null)

const earliestRecordTimestamp = $computed(() => records[0]?.timestamp ?? null)

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
  if (scrollElement != null) {
    containerInfo.scrollHeight = scrollElement.scrollHeight
    containerInfo.scrollWidth = scrollElement.scrollWidth
    containerInfo.scrollTop = scrollElement.scrollTop
    containerInfo.scrollLeft = scrollElement.scrollLeft
    containerInfo.clientHeight = scrollElement.clientHeight
    containerInfo.clientWidth = scrollElement.clientWidth
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
  const element = scrollElement
  element?.addEventListener('scroll', onScroll, { passive: true })
  void onScroll()
  onCleanup(() => {
    element?.removeEventListener('scroll', onScroll)
  })
})

function isNearTop() {
  if (scrollElement == null) {
    return false
  }

  return containerInfo.scrollTop <= recordsUntilNearTop * recordHeight
}

function isAtBottom() {
  if (scrollElement == null) {
    return true
  }

  return containerInfo.scrollTop + containerInfo.clientHeight >= containerInfo.scrollHeight - 2
}

const isAtBottomComputed = $computed(isAtBottom)

const isShowingVerticalScrollBar = $computed(() => {
  if (scrollElement == null) {
    return true
  }

  return containerInfo.scrollHeight > containerInfo.clientHeight
})

const isShowingHorizontalScrollBar = $computed(() => {
  if (scrollElement == null) {
    return true
  }

  return containerInfo.scrollWidth > containerInfo.clientWidth
})

async function delay(milliseconds = 0) {
  return await new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function prependRecords(prepended: Record[]) {
  const scrollTop = containerInfo.scrollTop
  const height = prepended.length * recordHeight
  records = [...prepended, ...records] as Record[]
  scroll?.refresh(-1)
  await nextTick()
  scrollElement?.scrollTo({
    top: scrollTop + height,
  })
  await nextTick()
}

async function appendRecords(appended: Record[]) {
  const follow = isAtBottom()
  let resort = false
  if (appended.length > 0 && records.length > 0) {
    if (appended[appended.length - 1].timestamp < records[records.length - 1].timestamp) {
      resort = true
    }
  }

  let buffer = [...records, ...appended] as Record[]
  if (resort) {
    buffer = _.sortBy(buffer, (record) => record.timestamp)
  }

  records = buffer

  if (follow) {
    if (records.length > recordCullThreshold) {
      records = records.slice(records.length - recordCullCount, records.length)
      await forceScrollToBottom(100)
    } else {
      scroll?.refresh(records.length + 1)
    }
  }

  await nextTick()
}

async function loadPrevious() {
  isLoadingPrevious = true

  const key = searchFilterKey
  try {
    const results: Record[] = await get({
      address: selector,
      search: searchFilter.search === '' ? undefined : searchFilter.search,
      search_field: searchFilter.field,
      before: earliestRecordTimestamp == null ? undefined : earliestRecordTimestamp,
      order: '-timestamp',
      limit: recordLoadSize,
    })

    if (key !== searchFilterKey) {
      return
    }

    isExhausted = results.length === 0
    await prependRecords(results.reverse())
  } finally {
    isLoadingPrevious = false
  }
}

async function loadCurrent() {
  updateContainerInfo()

  isLoadingCurrent = true
  records = []
  recordsStreamed = []

  const key = searchFilterKey
  try {
    const results: Record[] = await get({
      address: selector,
      search: searchFilter.search === '' ? undefined : searchFilter.search,
      search_field: searchFilter.field,
      order: '-timestamp',
      limit: recordLoadSizeInitial,
    })

    if (key !== searchFilterKey) {
      return
    }

    isExhausted = results.length === 0
    const appended = [...results.reverse(), ...recordsStreamed]
    await appendRecords(appended)
    lastLoadedCurrent = moment.utc()
    await forceScrollToBottom()
    updateContainerInfo()
  } finally {
    isLoadingCurrent = false
  }
}

function scrollToBottom() {
  if (scroll != null) {
    scroll.scrollTo(records.length)
  }
}

async function onScrollToBottomClicked() {
  records = records.slice(records.length - recordCullCount, records.length)
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
  records = []
  recordsStreamed = []
  isLoadingCurrent = true
  debouncedLoadCurrent()
})

const debouncedFilter = debouncedComputed(() => _.cloneDeep(searchFilter), 750)

useStream(
  computed(() => ({
    address: selector,
    search: debouncedFilter.value.search === '' ? undefined : debouncedFilter.value.search,
  })),
  async (record: Record) => {
    if (isLoadingCurrent) {
      recordsStreamed = [...recordsStreamed, record]
    } else {
      await appendRecords([record])
    }
  }
)

async function onSend(data: string) {
  console.log(data)
  // const result = await engine.messages.send(, data)
  // if (result.ok) {
  //   return
  // }
  // notify.error(`Message failed to send. ${JSON.stringify(result.error)}`)
}

// let columnWidths = $ref<number[]>([])
let latestRecordLoaded = $ref<VNodeRef | null>(null)

watch(
  computed(() => latestRecordLoaded),
  (element) => {
    // if (element == null) {
    //   return
    // }

    console.log(element.element.element)
    console.log(element.element.element)
  }
)

const columns = $computed(() => {
  const base = [
    { label: 'Timestamp', field: 'timestamp' },
    { label: 'Address', field: 'address' },
  ]
  switch (type) {
    case 'message':
      return [
        ...base,
        { label: 'Direction', field: 'direction' },
        { label: 'Content', field: 'content' },
      ]
    case 'alert':
      return [
        ...base,
        { label: 'Level', field: 'level' },
        { label: 'Code', field: 'code' },
        { label: 'Info', field: 'info' },
      ]
    case 'log-entry':
      return [...base, { label: 'Level', field: 'level' }, { label: 'Content', field: 'Content' }]
  }
})
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
    <div>
      <q-markup-table
        :ref="(table: any) => (tableElement = table?.$el ?? null)"
        :class="$style.headerTable"
        dense
        flat
        separator="cell"
      >
        <q-th
          :class="$style.header"
          :style="{ minWidth: `${context.headerWidth}px`, maxWidth: `${context.headerWidth}px` }"
        >
          <q-tr>
            <q-td
              v-for="(column, i) in columns"
              :key="column.field"
              :class="$style.headerColumn"
              :style="i < columns.length - 1 ? { width: `${context.getColumnWidth(i)}px` } : {}"
            >
              {{ column.label }}
            </q-td>
          </q-tr>
        </q-th>
      </q-markup-table>
    </div>
    <q-separator />
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
        <span v-else-if="records.length === 0" key="empty" class="absolute-center">
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
        :class="['fit', $style.virtualScroll, records.length === 0 && $style.virtualScrollEmpty]"
        dense
        flat
        :items="records"
        separator="cell"
        square
        type="table"
        :virtual-scroll-item-size="recordHeight"
        :virtual-scroll-slice-size="recordSliceSize"
      >
        <template #default="{ item }">
          <record-view-message
            v-if="type === 'message'"
            :key="(item as Message).id"
            :message="item"
          />
          <record-view-alert v-else-if="type === 'alert'" :key="(item as Alert).id" :alert="item" />
          <record-view-log-entry v-else :key="(item as LogEntry).id" :entry="item" />
        </template>
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
      <command-input v-if="address" :address @send="onSend" />
    </div>
  </section-card>
</template>

<style lang="scss" module>
.headerTable {
  width: 100%;
  height: 22px;
  overflow: hidden;
  contain: size;
}

.header {
  padding: 0px !important;
}

.headerColumn {
  padding: 2px 8px !important;
  text-align: left;
}

.virtualScrollContainer {
  contain: size !important; // This is needed for horizontal scrolling to work.
  position: relative;
}

.virtualScroll {
  overscroll-behavior: contain;
  opacity: 1;
  transition: opacity 0.25s ease-out;
  position: relative;
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
