<script lang="ts" setup>
import type { Alert } from '@/api/alerts'
import { highlight } from '@/utilities'

const { alert } = defineProps<{
  alert: Alert
}>()

const renderedData = $computed(() => highlight(JSON.stringify(alert.data), 'json'))
</script>

<template>
  <c-record-view-record :record="alert">
    <td class="w-0 min-w-14 text-center">
      <c-record-view-level-chip :level="alert.level" />
    </td>
    <td class="w-0 min-w-13">
      <div class="font-mono text-[9px] whitespace-nowrap">{{ alert.type }}</div>
    </td>
    <td>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="font-mono text-[9px] whitespace-nowrap" v-html="renderedData" />
    </td>
  </c-record-view-record>
</template>
