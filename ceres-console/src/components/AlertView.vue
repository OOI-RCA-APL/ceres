<template>
  <section-card :title="title">
    <template #header-append>
      <q-space class="gt-sm" />
      <div class="col-grow q-ml-sm self-search-input-container">
        <q-input v-model="search" class="alert-view-search-input" :debounce="50" dense outlined>
          <template #prepend>
            <q-icon name="search" />
          </template>
        </q-input>
      </div>
    </template>
    <div v-if="alerts.length" class="col-grow self-virtual-scroll-container">
      <q-virtual-scroll
        ref="scroll"
        v-slot="{ item: alert }"
        class="alert-view-virtual-scroll fit self-virtual-scroll"
        :items="alerts"
        :virtual-scroll-item-size="alertHeight"
        :virtual-scroll-slice-size="250"
      >
        <alert-view-item :key="alert.id" :alert="alert" />
      </q-virtual-scroll>
    </div>
    <div v-else-if="!isDoingInitialLoad" class="col-grow items-center justify-center row">
      <span class="self-empty-message-text text-italic">
        <template v-if="isShowingAll">No alerts were found.</template>
        <template v-else>No matching alerts were found.</template>
      </span>
    </div>
  </section-card>
</template>

<script lang="ts" setup>
import { Alert, ComponentInfo } from '@/api/models'
import { getAlerts, getComponent, useAlertStream } from '@/api/queries'
import AlertViewItem from '@/components/AlertViewItem.vue'
import SectionCard from '@/components/SectionCard.vue'
import { QVirtualScroll } from 'quasar'
import { computed, nextTick, onMounted, watch, watchEffect } from 'vue'

const { title, unitName, componentName } = defineProps<{
  title: string
  containerClass?: string | null
  unitName: string
  componentName: string
  square?: boolean
}>()

const info = (await getComponent(unitName, componentName)) as ComponentInfo
if (info == null) {
  throw new Error('Component not found')
}

const alertHeight = 21.5

let search = $ref('')
let scroll = $shallowRef<QVirtualScroll | null>(null)
const container = $computed(() => {
  if (scroll == null) {
    return null
  }

  return scroll.$el as HTMLDivElement
})

const isShowingAll = $computed(() => search.length === 0)

let alerts = $ref<Alert[]>([])

const earliestAlertTimestamp = $computed(() => alerts[0]?.timestamp ?? null)

let isExhausted = $ref(false)
let isDoingInitialLoad = $ref(true)
let isLoadingPreviousAlerts = $ref(false)
let isLoadingCurrentAlerts = $ref(false)

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

  if (isExhausted || isDoingInitialLoad || isLoadingCurrentAlerts || isLoadingPreviousAlerts) {
    return
  }

  try {
    isLoadingPreviousAlerts = true
    await loadPreviousAlerts()
  } finally {
    isLoadingPreviousAlerts = false
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

  return containerInfo.scrollTop < 20 * alertHeight
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

async function prependAlerts(prepended: Alert[]) {
  alerts = Object.freeze([...prepended, ...alerts]) as Alert[]
  scroll?.refresh(prepended.length)

  await delay(15)
  await nextTick()
  await delay()
  await nextTick()
}

async function appendAlerts(appended: Alert[]) {
  const follow = isAtBottom()
  alerts = Object.freeze([...alerts, ...appended]) as Alert[]
  if (follow) {
    scroll?.refresh(alerts.length)
  }

  await delay(50)
  await nextTick()
  await delay()
  await nextTick()

  if (follow) {
    scroll?.scrollTo(alerts.length, 'end-force')
  }
}

async function loadPreviousAlerts() {
  const results = await getAlerts({
    source: info.address,
    search: search === '' ? undefined : search,
    before: earliestAlertTimestamp == null ? undefined : earliestAlertTimestamp,
    order: 'new-to-old',
    limit: 100,
  })

  isExhausted = results.length === 0
  await prependAlerts(results.reverse())
}

async function loadCurrentAlerts() {
  const results = await getAlerts({
    source: info.address,
    search: search === '' ? undefined : search,
    order: 'new-to-old',
    limit: 100,
  })

  isExhausted = results.length === 0
  alerts = []
  await appendAlerts(results.reverse())
}

useAlertStream(
  computed(() => ({
    source: info.address,
    search: search === '' ? undefined : search,
  })),
  async (alert: Alert) => {
    await appendAlerts([alert])
  }
)

function scrollToBottom() {
  if (scroll != null) {
    scroll.scrollTo(alerts.length)
  }
}

onMounted(async () => {
  try {
    try {
      isDoingInitialLoad = true
      isLoadingCurrentAlerts = true
      await loadCurrentAlerts()
    } finally {
      isLoadingCurrentAlerts = false
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
    isLoadingCurrentAlerts = true
    await loadCurrentAlerts()
    scrollToBottom()
  } finally {
    isLoadingCurrentAlerts = false
  }
})
</script>

<style lang="scss" scoped>
.self-virtual-scroll-container {
  contain: size !important; // This is needed for horizontal scrolling to work.
}

.self-virtual-scroll {
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
.alert-view-search-input .q-field__control,
.alert-view-search-input .q-field__marginal {
  height: 28px;
}

.alert-view-search-input {
  left: 12px;
  position: absolute;
  top: -14px;
  width: 100%;
}

.alert-view-virtual-scroll .q-virtual-scroll__content {
  contain: unset !important;
}
</style>
