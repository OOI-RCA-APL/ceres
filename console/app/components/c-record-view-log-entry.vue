<script lang="ts" setup>
import type { LogEntry } from '@/api/logs'

const { entry } = defineProps<{
  entry: LogEntry
}>()
</script>

<template>
  <c-record-view-record :record="entry">
    <td class="w-0 min-w-14">
      <div class="justify-center">
        <c-record-view-level-chip :level="entry.level" />
      </div>
    </td>
    <td>
      <c-data-content class="w-full font-mono text-[9px] whitespace-nowrap" :data="entry.content" />
    </td>
  </c-record-view-record>
</template>
