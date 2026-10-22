<script lang="ts" setup>
import { computed, watch } from 'vue'

import { useAccess } from '@/api/access'
import type { Address } from '@/api/address'
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  describeExporter,
  describeExportRun,
  type ExporterInfo,
  isExportRunning,
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

// A component stopping or starting changes each schedule's next run, the same push the jobs
// section refetches on.
watch(
  () => engine.statuses.get(address),
  () => {
    void exportersQuery.refetch()
  },
)

const exporters = $computed(() => exportersQuery.data.value ?? [])

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
