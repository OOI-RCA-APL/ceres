<script lang="ts" setup>
import { useDocumentVisibility, useEventListener } from '@vueuse/core'
import { cloneDeep } from 'lodash-es'
import moment, { Moment } from 'moment'
import { debounce, QVirtualScroll } from 'quasar'
import { shallowReactive, nextTick, onMounted, reactive, watch, watchEffect, useSlots } from 'vue'

import { AddressSelector } from '@/api/address'
import { Alert } from '@/api/alerts'
import { useEngine } from '@/api/engine'
import { RecordFilter } from '@/api/entity'
import { LogEntry } from '@/api/logs'
import { Message } from '@/api/messages'
import { Particle } from '@/api/particles'
import { Record } from '@/api/shared'
import RecordViewAlert from '@/components/RecordViewAlert.vue'
import RecordViewLogEntry from '@/components/RecordViewLogEntry.vue'
import RecordViewMessage from '@/components/RecordViewMessage.vue'
import RecordViewParticle from '@/components/RecordViewParticle.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import { provideRecordViewContext } from '@/record-view'
import { debouncedComputed } from '@/utilities'
import { MessagesWidget, ParticlesWidget, AlertsWidget, LogsWidget } from '@/workspace'

type ColumnDefinition = {
  label: string
  name: string
  filtered?: boolean
  minWidth?: number
}

const {
  widget,
  filter,
  columns: appendedColumns,
} = defineProps<{
  widget: MessagesWidget | ParticlesWidget | AlertsWidget | LogsWidget
  columns: ColumnDefinition[]
  filter: RecordFilter
}>()

let isShowingAdvancedTimestampFilters = $ref(
  (widget.filter.after_hour ??
    widget.filter.before_hour ??
    widget.filter.after_minute ??
    widget.filter.before_minute) != null
)

const columns = $computed(() => [
  {
    label: 'Timestamp',
    name: 'timestamp',
    filtered:
      (widget.filter.after ??
        widget.filter.before ??
        widget.filter.timespan ??
        widget.filter.after_hour ??
        widget.filter.before_hour ??
        widget.filter.after_minute ??
        widget.filter.before_minute) != null,
    minWidth: 88,
  },
  { label: 'Address', name: 'address', filtered: widget.filter.address != null, minWidth: 72 },
  ...appendedColumns,
])

const engine = useEngine()
const slots = useSlots()

const get = $computed(() => {
  switch (widget.type) {
    case 'messages':
      return engine.messages.getAll
    case 'particles':
      return engine.particles.getAll
    case 'alerts':
      return engine.alerts.getAll
    case 'logs':
      return engine.logs.getAll
  }
})

const useStream = $computed(() => {
  switch (widget.type) {
    case 'messages':
      return engine.messages.useStream
    case 'particles':
      return engine.particles.useStream
    case 'alerts':
      return engine.alerts.useStream
    case 'logs':
      return engine.logs.useStream
  }
})

function getColumnFilterSlot(name: string) {
  return slots['column-filter-' + name]
}

function columnHasFilterMenu(name: string) {
  if (name === 'timestamp' || name === 'address') {
    return true
  }

  return getColumnFilterSlot(name) != null
}

let filterKey = $ref(0)
watch(
  () => JSON.stringify(filter),
  () => {
    filterKey++
  }
)
const filterIsEmpty = $computed(() => Object.values(filter).every((value) => value == null))

const context = provideRecordViewContext()

const recordsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / recordHeight))
const recordHeight = 24
const recordLoadSizeInitial = $computed(() => Math.min(recordsVisible + 50, 1000))
const recordLoadSize = $computed(() => Math.min(recordsVisible + 50, 1000))
const recordSliceSize = 25
const recordCullThreshold = $computed(() => recordsVisible + 500)
const recordCullCount = $computed(() => recordsVisible + 100)
const recordsUntilNearTop = 30

let scroll = $shallowRef<QVirtualScroll | null>(null)
let scrollElement = $shallowRef<HTMLDivElement | null>(null)

let tableElement = $ref<HTMLElement | null>(null)
watchEffect(() => {
  if (tableElement == null) {
    return
  }

  // Sync the scroll position of the header with the main table.
  tableElement.scrollLeft = containerInfo.scrollLeft
})

const records = shallowReactive<Record[]>([])
const recordsPending = shallowReactive<Record[]>([])
let lastLoadedCurrent = $shallowRef<Moment | null>(null)
let lastLoadedPrevious = $shallowRef<Moment | null>(null)

const earliestRecordTimestamp = $computed(() => records[0]?.timestamp ?? null)

const documentVisibility = $(useDocumentVisibility())
const isDocumentVisible = $computed(() => documentVisibility === 'visible')
let isDocumentJustVisible = $ref(false)

watch(
  () => isDocumentVisible,
  () => {
    if (isDocumentVisible) {
      isDocumentJustVisible = true
      setTimeout(() => {
        isDocumentJustVisible = false
      }, 500)

      if (isFollowing) {
        scrollToBottom(1000)
      }
    }
  }
)

let resizes = $ref(0)

useEventListener(window, 'resize', () => {
  const follow = isFollowing
  resizes++

  if (follow) {
    setTimeout(() => {
      nextTick(() => {
        scroll?.refresh()
        setTimeout(() => {
          nextTick(() => {
            scrollToBottom(1000)
            isFollowing = true
          })
        })
      })
    })
  }

  setTimeout(() => {
    resizes--
  }, 1000)
})

const isWindowJustResized = $computed(() => resizes > 0)

let isExhausted = $ref(false)
let isLoadingPrevious = $ref(false)
let isLoadingCurrent = $ref(true)

const containerInfo = reactive({
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

let scrollsToBottom = $ref(0)
const isScrollingToBottom = $computed(() => scrollsToBottom > 0)

async function scrollToBottom(duration = 1000, interval = 50) {
  function go() {
    updateContainerInfo()
    if (scroll != null) {
      scroll.scrollTo(records.length)
    }
    setTimeout(() => {
      nextTick(() => {
        if (scrollElement != null) {
          scrollElement.scrollTop = containerInfo.scrollHeight * 2
        }
      })
    })
  }

  scrollsToBottom++
  try {
    go()
    const id = setInterval(() => {
      go()
    }, interval)
    await delay(duration)
    clearInterval(id)
  } finally {
    scrollsToBottom--
  }
}

let isFollowing = $ref(true)

async function onScroll() {
  updateContainerInfo()
  if (isScrollingToBottom) {
    isFollowing = true
  } else if (!isDocumentJustVisible && !isWindowJustResized) {
    isFollowing = isAtBottom()
  }

  if (isExhausted || isLoadingCurrent || isLoadingPrevious || !isDocumentVisible) {
    return
  }

  if (lastLoadedCurrent == null || moment.utc().diff(lastLoadedCurrent) < 1000) {
    return
  }
  if (lastLoadedPrevious != null && moment.utc().diff(lastLoadedPrevious) < 1000) {
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
  records.splice(0, 0, ...prepended)
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

  records.push(...appended)
  if (resort) {
    records.sort((left, right) => left.timestamp.localeCompare(right.timestamp))
  }

  if (follow) {
    if (records.length > recordCullThreshold) {
      records.splice(0, records.length - recordCullCount)
      await scrollToBottom(100)
    } else {
      scroll?.refresh(records.length + 1)
      setTimeout(() => {
        nextTick(() => {
          scroll?.refresh(records.length + 1)
        })
      })
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
      order: 'timestamp:desc',
      limit: recordLoadSize,
    })

    if (key !== filterKey) {
      return
    }

    isExhausted = results.length === 0
    await prependRecords(results.reverse())
    lastLoadedPrevious = moment.utc()
  } finally {
    isLoadingPrevious = false
  }
}

async function loadCurrent() {
  updateContainerInfo()

  isLoadingCurrent = true
  records.splice(0)
  recordsPending.splice(0)

  const key = filterKey
  try {
    const results: Record[] = await get({
      ...filter,
      order: 'timestamp:desc',
      limit: recordLoadSizeInitial,
    })

    if (key !== filterKey) {
      return
    }

    isExhausted = results.length === 0
    const appended = [...results.reverse(), ...recordsPending]
    await appendRecords(appended)
    lastLoadedCurrent = moment.utc()
    await scrollToBottom()
    updateContainerInfo()
  } finally {
    isLoadingCurrent = false
  }
}

async function onScrollToBottomClicked() {
  records.splice(0, records.length - recordCullCount)
  await nextTick()
  await scrollToBottom(250)
}

onMounted(async () => {
  await loadCurrent()
})

const debouncedLoadCurrent = debounce(loadCurrent, 750)

watch(
  () => filterKey,
  async () => {
    records.splice(0)
    recordsPending.splice(0)
    isLoadingCurrent = true
    debouncedLoadCurrent()
  }
)

const debouncedFilter = debouncedComputed(() => cloneDeep(filter), 750)

useStream(debouncedFilter, async (record: Record) => {
  if (isLoadingCurrent) {
    recordsPending.push(record)
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
              :class="[$style.headerColumn, columnHasFilterMenu(column.name) && 'cursor-pointer']"
              :style="[
                i < columns.length - 1 ? { width: `${context.getColumnWidth(i)}px` } : {},
                { minWidth: column.minWidth != null ? `${column.minWidth}px` : undefined },
              ]"
            >
              <div class="items-center no-wrap row">
                <span :class="$style.headerColumnLabel">
                  {{ column.label }}
                </span>
                <q-icon
                  :class="[
                    $style.headerColumnGearIcon,
                    column.filtered && $style.headerColumnGearIconEdited,
                  ]"
                  :name="icons.settings"
                  size="10px"
                />
              </div>
              <q-menu
                v-if="columnHasFilterMenu(column.name)"
                anchor="top left"
                :offset="[0, 4]"
                self="bottom left"
              >
                <q-card bordered class="q-pa-xs" flat>
                  <div
                    v-if="column.name === 'timestamp'"
                    class="column q-gutter-xs"
                    style="min-width: 510px"
                  >
                    <div class="row">
                      <schema-form-value
                        v-model="widget.filter.after"
                        class="col q-mr-xs"
                        :schema="{
                          title: 'After',
                          type: 'string',
                          format: 'date-time',
                          optional: true,
                        }"
                      />
                      <schema-form-value
                        v-model="widget.filter.before"
                        class="col"
                        :schema="{
                          title: 'Before',
                          type: 'string',
                          format: 'date-time',
                          optional: true,
                        }"
                      />
                    </div>
                    <div class="items-center relative-position row">
                      <q-btn
                        class="full-width row"
                        flat
                        size="0"
                        style="padding: 0 2px"
                        @click="
                          isShowingAdvancedTimestampFilters = !isShowingAdvancedTimestampFilters
                        "
                      >
                        <q-tooltip>
                          {{ isShowingAdvancedTimestampFilters ? 'Hide' : 'Show' }} Advanced
                        </q-tooltip>
                        <q-separator class="col q-mr-xs" />
                        <q-icon
                          :name="isShowingAdvancedTimestampFilters ? icons.menuUp : icons.menuDown"
                          size="12px"
                        />
                        <q-separator class="col q-ml-xs" />
                      </q-btn>
                    </div>
                    <template v-if="isShowingAdvancedTimestampFilters">
                      <div class="row">
                        <schema-form-value
                          v-model="widget.filter.after_hour"
                          class="col q-mr-xs"
                          :schema="{
                            title: 'After Hour',
                            type: 'integer',
                            optional: true,
                            minimum: 0,
                            exclusiveMaximum: 24,
                          }"
                        />
                        <schema-form-value
                          v-model="widget.filter.before_hour"
                          class="col"
                          :schema="{
                            title: 'Before Hour',
                            type: 'integer',
                            optional: true,
                            minimum: 0,
                            exclusiveMaximum: 24,
                          }"
                        />
                      </div>
                      <div class="row">
                        <schema-form-value
                          v-model="widget.filter.after_minute"
                          class="col q-mr-xs"
                          :schema="{
                            title: 'After Minute',
                            type: 'integer',
                            optional: true,
                            minimum: 0,
                            exclusiveMaximum: 60,
                          }"
                        />
                        <schema-form-value
                          v-model="widget.filter.before_minute"
                          class="col"
                          :schema="{
                            title: 'Before Minute',
                            type: 'integer',
                            optional: true,
                            minimum: 0,
                            exclusiveMaximum: 60,
                          }"
                        />
                      </div>
                    </template>
                  </div>
                  <div v-else-if="column.name === 'address'" style="min-width: 200px">
                    <schema-form-value
                      :model-value="widget.filter.address?.toString()"
                      :schema="{
                        title: 'Address',
                        type: 'string',
                        enum: engine.components.all.flatMap((current) => [
                          current.address.toString(),
                          current.address.all().toString(),
                        ]),
                        optional: true,
                      }"
                      @update:model-value="
                        (value: any) =>
                          (widget.filter.address =
                            value == null ? undefined : new AddressSelector(String(value)))
                      "
                    />
                  </div>
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
            No {{ filterIsEmpty ? '' : 'matching' }} {{ widget.type }}
            found.
          </span>
        </span>
      </transition-group>
      <q-virtual-scroll
        :ref="(instance: QVirtualScroll | null) => {
          scroll = instance;
          scrollElement = instance?.$el as HTMLDivElement;
        }"
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
            v-if="widget.type === 'messages'"
            :key="(item as Message).id"
            :message="item"
          />
          <record-view-particle
            v-else-if="widget.type === 'particles'"
            :key="(item as Particle).id"
            :particle="item"
          />
          <record-view-alert
            v-else-if="widget.type === 'alerts'"
            :key="(item as Alert).id"
            :alert="item"
          />
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

.headerColumn:hover {
  .headerColumnLabel {
    opacity: 0.5;
  }
  .headerColumnGearIcon {
    opacity: 0.25;
  }
}

.headerColumnGearIconEdited {
  opacity: 1 !important;
  color: $primary;
}

.headerColumnGearIcon {
  opacity: 0;
  margin-left: 4px;
  margin-right: -4px;
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
