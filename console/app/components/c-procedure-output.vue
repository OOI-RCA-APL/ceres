<script lang="ts" setup>
import { displayDuration, useTime } from '@/time'
import type { Datetime } from '@/time'

const { value, sentAt, receivedAt } = defineProps<{
  value: unknown
  sentAt: Datetime | null
  receivedAt: Datetime | null
}>()

const time = useTime()

const json = $computed(() => {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
})
</script>

<!-- What a procedure returned, with how long ago it came back and how long it took. -->
<template>
  <div>
    <div class="mb-1 flex items-baseline gap-1">
      <c-text variant="th">Output</c-text>
      <c-text v-if="receivedAt != null" class="opacity-50" variant="description">
        {{ displayDuration(time.now.diff(receivedAt, 'second'), { short: true }) }} ago
      </c-text>
      <c-text v-if="receivedAt != null && sentAt != null" class="opacity-50" variant="description">
        &middot; {{ displayDuration(receivedAt.diff(sentAt) / 1000, { short: true }) }}
      </c-text>
    </div>
    <c-textarea
      class="w-full"
      :model-value="json ?? 'null'"
      readonly
      :rows="8"
      :ui="{ base: 'font-mono text-[11px]' }"
    />
  </div>
</template>
