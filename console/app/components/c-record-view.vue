<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { useDocumentVisibility, useEventListener } from '@vueuse/core'
import { debounce } from 'lodash-es'
import { nextTick, onMounted, reactive, watch, watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import type { Record } from '@/api/entity'
import CFilterBar from '@/components/c-filter-bar.vue'
import { recordRowHeight } from '@/components/c-record-view-record.vue'
import { compileQuery, hasValue, seedQueryFromFilter } from '@/filters/compile'
import { definitionsForColumn } from '@/filters/definitions'
import type { RecordKind } from '@/filters/definitions'
import { flattenQuery, isBlock } from '@/filters/model'
import icons from '@/icons'
import { orderedHiddenColumns, provideRecordViewContext } from '@/record-view'
import { createRecordFeed } from '@/records/feed'
import { debouncedComputed } from '@/utilities'
import { useWorkspace } from '@/workspace'
import type { AlertsWidget, LogsWidget, MessagesWidget, ParticlesWidget } from '@/workspace'

export type ColumnDefinition = {
  label: string
  name: string
  minWidth?: number
}

const { widget, columns: appendedColumns } = defineProps<{
  widget: MessagesWidget | ParticlesWidget | AlertsWidget | LogsWidget
  columns: ColumnDefinition[]
}>()

const engine = useEngine()
const workspace = useWorkspace()

const recordKind = $computed<RecordKind>(() => widget.type)

// A workspace saved before the bar existed carries only the flat filter, which seeds the
// bar once and is compiled back from it from then on.
if (widget.query.length === 0 && Object.values(widget.filter).some(hasValue)) {
  widget.query = seedQueryFromFilter(widget.filter, widget.type)
}

const compiledFilter = $computed(() => compileQuery(widget.query))

// The flat part keeps the stored filter readable by the old console while both ship.
watch(
  () => compiledFilter,
  (compiled) => {
    widget.filter = compiled as typeof widget.filter
  },
)

/** The compiled filter with its address selector resolved through the workspace. */
const resolvedFilter = $computed(() => ({
  ...compiledFilter,
  address: workspace.resolveFilterAddress(compiledFilter.address as never),
}))

// The address filter offers each component and its subtree selector, narrowed to the
// workspace's placement so it matches what the record APIs can actually return.
const addressFilterOptions = $computed(() =>
  engine.components.all
    .filter((component) => workspace.isWithinScope(component.address))
    .flatMap((component) => [component.address.toString(), component.address.all().toString()]),
)

const columns = $computed(() => [
  { label: 'Timestamp', name: 'timestamp', minWidth: 88 },
  { label: 'Address', name: 'address', minWidth: 64 },
  ...appendedColumns,
])

// Both read from the definitions rather than from the stored names, so a workspace holding a
// column this view no longer defines neither counts towards the chip nor fills the menu with
// an entry that would restore nothing.
const visibleColumns = $computed(() =>
  columns.filter((column) => !widget.hiddenColumns.includes(column.name)),
)
const hiddenColumns = $computed(() =>
  columns.filter((column) => widget.hiddenColumns.includes(column.name)),
)

function hideColumn(name: string) {
  widget.hiddenColumns = orderedHiddenColumns(columns, [...widget.hiddenColumns, name])
}

function showColumn(name: string) {
  const hidden = new Set(widget.hiddenColumns)
  hidden.delete(name)
  widget.hiddenColumns = orderedHiddenColumns(columns, hidden)
}

const hiddenColumnItems = $computed<DropdownMenuItem[]>(() =>
  hiddenColumns.map((column) => ({
    label: column.label,
    icon: icons.view,
    onSelect: () => showColumn(column.name),
  })),
)

/** The bar's conditions, wherever they nest, for marking filtered columns. */
const activeKinds = $computed(() => {
  const kinds = new Set<string>()
  for (const item of flattenQuery(widget.query)) {
    if (!isBlock(item) && hasValue(item.value)) {
      kinds.add(item.kind)
    }
  }

  return kinds
})

function columnIsFiltered(name: string): boolean {
  return definitionsForColumn(recordKind, name).some((definition) =>
    activeKinds.has(definition.kind),
  )
}

let filterBar = $ref<InstanceType<typeof CFilterBar> | null>(null)

function columnMenuItems(name: string): DropdownMenuItem[][] {
  const filters = definitionsForColumn(recordKind, name).map((definition) => ({
    label: definition.label,
    icon: icons.filter,
    onSelect: () => filterBar?.appendKind(definition.kind),
  }))

  // The last column keeps no hide, a view drawn with no columns leaving nothing to bring one
  // back from.
  const hide =
    visibleColumns.length > 1
      ? [{ label: 'Hide', icon: icons.hide, onSelect: () => hideColumn(name) }]
      : []

  return [filters, hide].filter((group) => group.length > 0)
}

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

let filterKey = $ref(0)
watch(
  () => JSON.stringify(resolvedFilter),
  () => {
    filterKey++
  },
)
const filterIsEmpty = $computed(() => widget.query.length === 0)

const context = provideRecordViewContext(() => widget.hiddenColumns)

const recordHeight = recordRowHeight
const recordsVisible = $computed(() => Math.ceil(containerInfo.clientHeight / recordHeight))
const recordLoadSize = $computed(() => Math.min(recordsVisible + 50, 1000))
// Screenfuls kept drawn above and below the ones on screen. Nothing here is measured so a
// row held in reserve costs only the drawing of it.
const recordOverscan = 2
const recordCullThreshold = $computed(() => recordsVisible + 500)
const recordCullCount = $computed(() => recordsVisible + 100)
// How far above the top the records above start being fetched. Deep enough that the request
// has long landed before the top is reached so arriving there shows records rather than a
// wait.
const recordsUntilNearTop = 400

// How far above the top the records above are actually put in. Short of the top rather than
// at it so a scroll still travelling runs straight on into them instead of arriving at the
// end of the list while they are placed.
const recordsUntilPlacingPrevious = 60

const feed = createRecordFeed<Record>({
  getAll: (filter) => get(filter as never),
  filter: () => resolvedFilter,
  pageSize: () => recordLoadSize,
})

const records = feed.rows
const isLoadingCurrent = $(feed.isLoadingCurrent)

let scroll = $shallowRef<{
  scrollTo: (index: number) => void
  moveTo: (top: number) => void
  refresh: () => void
} | null>(null)
let scrollElement = $shallowRef<HTMLElement | null>(null)

let tableElement = $ref<HTMLElement | null>(null)
watchEffect(() => {
  if (tableElement == null) {
    return
  }

  // Sync the scroll position of the header with the main table.
  tableElement.scrollLeft = containerInfo.scrollLeft
})

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
  },
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
          scroll?.moveTo(containerInfo.scrollHeight * 2)
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

/** When the scroller last moved for any reason, marking a scroll in progress. */
let lastScrolledAt = 0

/** Where the scroller stood at the previous event, for telling a move up from a move down. */
let previousScrollTop = 0

async function onScroll() {
  lastScrolledAt = performance.now()
  const previous = previousScrollTop
  updateContainerInfo()
  previousScrollTop = containerInfo.scrollTop

  // Following ends on a move upwards alone. A record landing between the move to the end and the
  // event announcing it grows the list underneath, which position on its own reads as leaving.
  if (isScrollingToBottom) {
    isFollowing = true
  } else if (!isDocumentJustVisible && !isWindowJustResized) {
    if (isAtBottom()) {
      isFollowing = true
    } else if (containerInfo.scrollTop < previous - 1) {
      isFollowing = false
    }
  }

  if (isLoadingCurrent || !isDocumentVisible) {
    return
  }

  // Fetched well before they are wanted so reaching the top does not mean waiting on a
  // request.
  if (isWithinReachOfTop()) {
    void fetchPrevious()
  }

  // Held back until the scroll is over, or until they are the only thing left to show.
  // Putting them in grows the scrollable extent, and a scrollbar's thumb is sized and placed
  // by that extent so growing it mid-gesture is what the thumb shows as a jump.
  if (feed.bufferedCount.value > 0) {
    if (isCloseToTop()) {
      void placePrevious()
    } else {
      placePreviousOnceStill()
    }
  }
}

/** How long the scroller must hold still before the list may grow underneath it. */
const stillnessBeforeLoading = 180

let placePreviousTimer: ReturnType<typeof setTimeout> | null = null

function placePreviousOnceStill() {
  if (placePreviousTimer != null) {
    return
  }

  placePreviousTimer = setTimeout(() => {
    placePreviousTimer = null

    if (feed.bufferedCount.value === 0) {
      return
    }

    // Still moving so wait out another stretch of quiet rather than growing the list now.
    if (performance.now() - lastScrolledAt < stillnessBeforeLoading) {
      placePreviousOnceStill()
      return
    }

    void placePrevious()
  }, stillnessBeforeLoading)
}

watchEffect((onCleanup) => {
  const element = scrollElement
  element?.addEventListener('scroll', onScroll, { passive: true })
  void onScroll()
  onCleanup(() => {
    element?.removeEventListener('scroll', onScroll)
  })
})

/** Close enough to the top that the records above ought to be on their way. */
function isWithinReachOfTop() {
  if (scrollElement == null) {
    return false
  }

  return containerInfo.scrollTop <= recordsUntilNearTop * recordHeight
}

/** Close enough to the top that the records above are wanted now, before the top is
reached. */
function isCloseToTop() {
  if (scrollElement == null) {
    return false
  }

  return containerInfo.scrollTop <= recordsUntilPlacingPrevious * recordHeight
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

async function fetchPrevious() {
  await feed.fetchPrevious()

  // The top may have been come up on while these were still on their way, and there is
  // nothing above to scroll to that would ask for them again so they go in the moment they
  // land.
  if (feed.bufferedCount.value > 0 && isCloseToTop()) {
    await placePrevious()
  }
}

// Older records arrive above whatever is on screen, which would carry it down the list by
// exactly their height. Adding that height back leaves the same records under the eye so a
// scroll upwards runs on rather than jumping.
async function placePrevious() {
  // Asked of the element rather than of the last reading taken from it. A reading is only as
  // new as the last scroll event, and a scroll still under way has moved on since.
  const scrollTop = scrollElement?.scrollTop ?? containerInfo.scrollTop
  const placed = feed.placePrevious()
  if (placed === 0) {
    return
  }

  // Only once the rows are there can the position move past where they end since a box
  // refuses to scroll further than it reaches.
  await nextTick()
  scroll?.moveTo(scrollTop + placed * recordHeight)
  await nextTick()
}

async function followAppends() {
  if (records.length > recordCullThreshold) {
    feed.cull(recordCullCount)
    await scrollToBottom(100)
  } else {
    scroll?.scrollTo(records.length)
    await nextTick()
    scroll?.scrollTo(records.length)
  }
}

async function loadCurrent() {
  updateContainerInfo()
  await feed.loadCurrent()
  await scrollToBottom()
  updateContainerInfo()
}

async function onScrollToBottomClicked() {
  feed.cull(recordCullCount)
  await nextTick()
  await scrollToBottom(250)
}

onMounted(async () => {
  await loadCurrent()
})

const debouncedLoadCurrent = debounce(loadCurrent, 750)

watch(
  () => filterKey,
  () => {
    feed.reset()
    debouncedLoadCurrent()
  },
)

const debouncedFilter = debouncedComputed(() => ({ ...resolvedFilter }), 750)

/** Whether arriving records should wait rather than land in the list right away.

A record appended mid-scroll grows the list under the scrollbar, and the thumb recomputing
against a new total once or twice a second reads as stutter. The new records belong below
the viewport of someone reading history so nothing visible is lost by holding them until the
scrolling pauses. At the bottom the view is following and the whole point is watching them
arrive.
*/
function shouldHoldAppends() {
  return !isFollowing && performance.now() - lastScrolledAt < 400
}

let pendingFlushTimer: ReturnType<typeof setTimeout> | null = null

function flushPendingSoon() {
  if (pendingFlushTimer != null) {
    return
  }

  pendingFlushTimer = setTimeout(async () => {
    pendingFlushTimer = null
    if (feed.pendingCount.value === 0) {
      return
    }

    if (isLoadingCurrent || shouldHoldAppends()) {
      flushPendingSoon()
      return
    }

    const flushed = feed.flushPending()
    if (flushed.length > 0 && isFollowing) {
      await followAppends()
    }
  }, 300)
}

useStream(debouncedFilter as never, async (record: Record) => {
  const outcome = feed.receive(record, shouldHoldAppends())
  if (outcome === 'held') {
    flushPendingSoon()
  } else if (isFollowing) {
    await followAppends()
  }
})
</script>

<template>
  <div class="border-default flex h-full flex-col rounded-md border">
    <c-filter-bar
      ref="filterBar"
      v-model="widget.query"
      :address-options="addressFilterOptions"
      :record-kind="recordKind"
    />
    <c-separator />
    <div class="flex">
      <div
        :ref="(header) => (tableElement = (header as HTMLElement) ?? null)"
        class="h-4.75 min-w-0 grow overflow-hidden"
        style="contain: size"
      >
        <div
          class="flex"
          :style="{ minWidth: `${context.headerWidth}px`, maxWidth: `${context.headerWidth}px` }"
        >
          <template v-for="(column, i) in visibleColumns" :key="column.name">
            <c-dropdown-menu :items="columnMenuItems(column.name)" size="sm">
              <button
                :class="[
                  'group border-default flex h-4.75 cursor-pointer items-center',
                  'border-r px-2 text-left text-[10px] last:border-r-0',
                  // The last column is given no width, so it takes what the sized ones leave
                  // and the header reaches as far as the rows under it.
                  i === visibleColumns.length - 1 && 'grow',
                ]"
                :style="[
                  i < visibleColumns.length - 1 ? { width: `${context.getColumnWidth(i)}px` } : {},
                  { minWidth: column.minWidth != null ? `${column.minWidth}px` : undefined },
                ]"
                type="button"
              >
                <span class="group-hover:opacity-50">{{ column.label }}</span>
                <c-icon
                  class="-mr-1 ml-1 opacity-0 group-hover:opacity-25"
                  :class="columnIsFiltered(column.name) && 'text-primary opacity-100!'"
                  :name="icons.filter"
                  size="9.5"
                />
              </button>
            </c-dropdown-menu>
          </template>
        </div>
      </div>
      <!-- Beside the header rather than over it, so the count stays put while the columns
      scroll under it and needs no background of its own to stay readable. -->
      <c-dropdown-menu v-if="hiddenColumns.length > 0" :items="hiddenColumnItems" size="sm">
        <button
          :class="[
            'border-default text-muted hover:text-default flex h-4.75 shrink-0 cursor-pointer',
            'items-center gap-1 border-l pr-1.5 pl-2 text-[10px] whitespace-nowrap',
          ]"
          type="button"
        >
          {{ hiddenColumns.length }} Hidden
          <c-icon :name="icons.chevronDown" size="9.5" />
        </button>
      </c-dropdown-menu>
    </div>
    <c-separator />
    <div class="relative grow" style="contain: size">
      <div
        v-if="isLoadingCurrent"
        class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"
      >
        <c-page-spinner />
      </div>
      <span
        v-else-if="records.length === 0"
        class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"
      >
        <span class="text-[13px] italic opacity-50">
          No {{ filterIsEmpty ? '' : 'matching' }} {{ widget.type }} found.
        </span>
      </span>
      <c-record-scroller
        :ref="
          (instance: any) => {
            scroll = instance
            scrollElement = instance?.element ?? null
          }
        "
        class="h-full w-full transition-opacity duration-250"
        :class="records.length === 0 && 'opacity-0'"
        :item-size="recordHeight"
        :items="records"
        :overscan="recordOverscan"
        style="overscroll-behavior: contain"
      >
        <template #default="{ item }">
          <c-record-view-message
            v-if="widget.type === 'messages'"
            :key="(item as Record).id"
            :data-display="(widget as MessagesWidget).dataDisplay"
            :message="item as never"
          />
          <c-record-view-particle
            v-else-if="widget.type === 'particles'"
            :key="(item as Record).id"
            :particle="item as never"
          />
          <c-record-view-alert
            v-else-if="widget.type === 'alerts'"
            :key="(item as Record).id"
            :alert="item as never"
          />
          <c-record-view-log-entry v-else :key="(item as Record).id" :entry="item as never" />
        </template>
      </c-record-scroller>
      <c-button
        v-if="!isLoadingCurrent && !isFollowing"
        class="absolute z-1"
        color="primary"
        :icon="icons.arrowDown"
        size="sm"
        square
        :style="{
          right: isShowingVerticalScrollBar ? '20px' : '4px',
          bottom: isShowingHorizontalScrollBar ? '20px' : '4px',
        }"
        @click="onScrollToBottomClicked"
      />
    </div>
    <slot />
  </div>
</template>
