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
    <c-record-view-cell class="w-0 min-w-14" name="level">
      <div class="justify-center">
        <c-record-view-level-chip :level="alert.level" />
      </div>
    </c-record-view-cell>
    <c-record-view-cell class="w-0 min-w-13" name="type">
      <div class="font-mono text-[9px] whitespace-nowrap">{{ alert.type }}</div>
    </c-record-view-cell>
    <c-record-view-cell name="data">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="font-mono text-[9px] whitespace-nowrap" v-html="renderedData" />
    </c-record-view-cell>
  </c-record-view-record>
</template>
