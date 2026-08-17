<script lang="ts" setup>
import type { LogEntry } from '@/api/logs'

const { entry } = defineProps<{
  entry: LogEntry
}>()
</script>

<template>
  <c-record-view-record :record="entry">
    <c-record-view-cell class="w-0 min-w-14" name="level">
      <div class="justify-center">
        <c-record-view-level-chip :level="entry.level" />
      </div>
    </c-record-view-cell>
    <c-record-view-cell name="content">
      <c-data-content class="w-full font-mono text-[9px] whitespace-nowrap" :data="entry.content" />
    </c-record-view-cell>
  </c-record-view-record>
</template>
