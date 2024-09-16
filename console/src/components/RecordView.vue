<script lang="ts" setup>
import { useDocumentVisibility } from '@vueuse/core'
import _ from 'lodash'
import moment, { Moment } from 'moment'
import { debounce, QVirtualScroll } from 'quasar'
import { computed, nextTick, onMounted, watch, watchEffect } from 'vue'

import { Address } from '@/api/address'
import { Alert } from '@/api/alerts'
import { useEngine } from '@/api/engine'
import { RecordFilter } from '@/api/entity'
import { LogEntry } from '@/api/log-entries'
import { Message } from '@/api/messages'
import { Record } from '@/api/shared'
import RecordViewAlert from '@/components/RecordViewAlert.vue'
import RecordViewLogEntry from '@/components/RecordViewLogEntry.vue'
import RecordViewMessage from '@/components/RecordViewMessage.vue'
import icons from '@/icons'
import { provideRecordViewContext } from '@/record-view'
import { debouncedComputed } from '@/utilities'

type ColumnDefinition = {
  label: string
  name: string
  filtered?: boolean
}

const { type, filter } = defineProps<{
  containerClass?: string | null
  address?: Address | null
  type: 'alert' | 'message' | 'log-entry'
  columns: ColumnDefinition[]
  filter: RecordFilter
}>()

const engine = useEngine()

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

let filterKey = $ref(0)
watch(
  computed(() => JSON.stringify(filter)),
  () => {
    filterKey++
  }
)

const context = provideRecordViewContext()

const recordsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / recordHeight))
const recordHeight = 24
const recordLoadSizeInitial = $computed(() => Math.min(recordsVisible + 50, 1000))
const recordLoadSize = $computed(() => Math.min(recordsVisible + 50, 1000))
const recordSliceSize = 250
const recordCullThreshold = $computed(() => recordsVisible + 500)
const recordCullCount = $computed(() => recordsVisible + 100)
const recordsUntilNearTop = 30

let isFollowing = $ref(true)
let isScrollingToBottom = $ref(false)

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

const documentVisibility = $(useDocumentVisibility())
const isDocumentVisible = $computed(() => documentVisibility === 'visible')
let isDocumentJustVisible = $ref(false)

watch(
  computed(() => isDocumentVisible),
  () => {
    if (isDocumentVisible) {
      isDocumentJustVisible = true
      setTimeout(() => {
        isDocumentJustVisible = false
      }, 500)

      if (isFollowing) {
        scrollToBottom()
      }
    }
  }
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
  if (isScrollingToBottom) {
    isFollowing = true
  } else if (!isDocumentJustVisible) {
    isFollowing = isAtBottom()
  }

  if (isExhausted || isLoadingCurrent || isLoadingPrevious || !isDocumentVisible) {
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
  const follow = isFollowing
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
      await scrollToBottom(100)
    } else {
      scroll?.refresh(records.length + 1)
    }
  }

  await nextTick()
}

async function loadPrevious() {
  isLoadingPrevious = true

  const key = filterKey
  try {
    const results: Record[] = await get({
      ...filter,
      before: earliestRecordTimestamp == null ? filter.before : earliestRecordTimestamp,
      order: '-timestamp',
      limit: recordLoadSize,
    })

    if (key !== filterKey) {
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

  const key = filterKey
  try {
    const results: Record[] = await get({
      ...filter,
      order: '-timestamp',
      limit: recordLoadSizeInitial,
    })

    if (key !== filterKey) {
      return
    }

    isExhausted = results.length === 0
    const appended = [...results.reverse(), ...recordsStreamed]
    await appendRecords(appended)
    lastLoadedCurrent = moment.utc()
    await scrollToBottom()
    updateContainerInfo()
  } finally {
    isLoadingCurrent = false
  }
}

async function onScrollToBottomClicked() {
  records = records.slice(records.length - recordCullCount, records.length)
  await nextTick()
  await scrollToBottom(250)
}

async function scrollToBottom(duration = 500, interval = 50) {
  function go() {
    if (scroll != null) {
      scroll.scrollTo(records.length)
    }
  }

  isScrollingToBottom = true
  try {
    go()
    const id = setInterval(() => {
      go()
    }, interval)
    await delay(duration)
    clearInterval(id)
  } finally {
    isScrollingToBottom = false
  }
}

onMounted(async () => {
  await loadCurrent()
})

const debouncedLoadCurrent = debounce(loadCurrent, 750)

watch($$(filterKey), async () => {
  records = []
  recordsStreamed = []
  isLoadingCurrent = true
  debouncedLoadCurrent()
})

const debouncedFilter = debouncedComputed(() => _.cloneDeep(filter), 750)

useStream(debouncedFilter, async (record: Record) => {
  if (isLoadingCurrent) {
    recordsStreamed = [...recordsStreamed, record]
  } else {
    await appendRecords([record])
  }
})
</script>

<template>
  <q-card bordered class="column q-pa-none" flat>
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
              :key="column.name"
              :class="[
                $style.headerColumn,
                $slots['column-filter-' + column.name] && 'cursor-pointer',
              ]"
              :style="i < columns.length - 1 ? { width: `${context.getColumnWidth(i)}px` } : {}"
            >
              <span>
                {{ column.label }}
              </span>
              <span v-if="column.filtered" class="text-primary"> *</span>
              <q-menu
                v-if="$slots['column-filter-' + column.name]"
                anchor="top left"
                class="no-shadow"
                :offset="[0, 4]"
                self="bottom left"
              >
                <q-card bordered class="q-pa-xs" flat>
                  <slot :name="'column-filter-' + column.name" />
                </q-card>
              </q-menu>
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
            No matching {{ type.replace('log-entry', 'log entrie') }}s were found.
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
          v-if="!isLoadingCurrent && !isFollowing"
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
    <slot />
  </q-card>
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
  height: 22px;
}

.headerColumnFilter {
  padding: 0 !important;
  text-align: left;
  height: 22px;
  flex: 1;
  flex-direction: row;
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
