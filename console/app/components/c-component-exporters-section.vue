<script lang="ts" setup>
import { computed, watch } from 'vue'

import { useAccess } from '@/api/access'
import type { Address } from '@/api/address'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  describeExporter,
  describeExportRun,
  describePlayback,
  type ExporterInfo,
  isExportRunning,
  isPlaybackRunning,
  type PlaybackRecord,
} from '@/api/exporters'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'

const { address } = defineProps<{ address: Address }>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

const access = useAccess()
const dialogs = useDialogs()
const engine = useEngine()

// Each run's record changes while it goes, so the listing polls once a second until every run
// has ended, and stops in a hidden tab.
const exportersQuery = useQuery({
  queryKey: computed(() => ['component-exporters', address.toString()]),
  queryFn: () => engine.components.getExporters(address),
  retry: false,
  refetchInterval: (query: { state: { data?: ExporterInfo[] } }) =>
    isExportRunning(query.state.data) ? 1000 : false,
})

// A playback's record changes while it goes, polled like the exporters' runs.
const playbacksQuery = useQuery({
  queryKey: computed(() => ['component-playbacks', address.toString()]),
  queryFn: () => engine.components.getPlaybacks(address),
  retry: false,
  refetchInterval: (query: { state: { data?: PlaybackRecord[] } }) =>
    isPlaybackRunning(query.state.data) ? 1000 : false,
})

// A component stopping or starting changes each schedule's next run, the same push the jobs
// section refetches on.
watch(
  () => engine.statuses.get(address),
  () => {
    void exportersQuery.refetch()
  },
)

const exporters = $computed(() => exportersQuery.data.value ?? [])

const lastPlayback = $computed(() => playbacksQuery.data.value?.[0])

const canManage = $computed(() => access.canManage(address.toString()))

const playbackBlockedReason = $computed(() => {
  if (!canManage) {
    return 'A playback needs manage access.'
  }

  return running ? null : 'A playback needs the component running.'
})

function playBack() {
  // The playback's export runs show on the exporters, so both listings refetch.
  dialogs.playBack({ address }).onOk(() => {
    void playbacksQuery.refetch()
    void exportersQuery.refetch()
  })
}

const running = $computed(() => engine.statuses.get(address)?.running ?? false)

const canOperate = $computed(() => access.canOperate(address.toString()))

const blockedReason = $computed(() => {
  if (!canOperate) {
    return 'Rebuilding needs operate access.'
  }

  return running ? null : 'Rebuilding needs the component running.'
})

function rebuild(exporter: ExporterInfo) {
  // The refetch picks up the new run's record at once, which starts the polling.
  dialogs.runExporter({ address, exporter }).onOk(() => {
    void exportersQuery.refetch()
  })
}
</script>

<template>
  <c-detail-section v-model:expanded="expanded" :title="`Exporters (${exporters.length})`">
    <c-list-item>
      <div class="grow">
        <c-text variant="body3">Playback</c-text>
        <c-text variant="description">Last playback: {{ describePlayback(lastPlayback) }}</c-text>
      </div>
      <c-tooltip :disabled="playbackBlockedReason == null" :text="playbackBlockedReason ?? ''">
        <c-button
          :disabled="playbackBlockedReason != null"
          :icon="icons.revertToOriginal"
          label="Play Back"
          size="xs"
          variant="soft"
          @click="playBack()"
        />
      </c-tooltip>
    </c-list-item>
    <c-text v-if="exporters.length === 0" class="px-3" variant="description">
      No exporters.
    </c-text>
    <c-list-item v-for="exporter in exporters" :key="exporter.name">
      <div class="grow">
        <c-text variant="body3">{{ exporter.name }}</c-text>
        <c-text variant="description">{{ describeExporter(exporter) }}</c-text>
        <c-text variant="description">
          Last run: {{ describeExportRun(exporter.last_run) }}
        </c-text>
      </div>
      <c-tooltip :disabled="blockedReason == null" :text="blockedReason ?? ''">
        <c-button
          :disabled="blockedReason != null"
          :icon="icons.refresh"
          label="Rebuild"
          size="xs"
          variant="soft"
          @click="rebuild(exporter)"
        />
      </c-tooltip>
    </c-list-item>
  </c-detail-section>
</template>
