<script lang="ts" setup>
import { useClipboard } from '@vueuse/core'

import icons from '@/icons'
import { displayDuration, useTime } from '@/time'
import type { Datetime } from '@/time'
import { highlight } from '@/utilities'

const { value, sentAt, receivedAt } = defineProps<{
  value: unknown
  sentAt: Datetime | null
  receivedAt: Datetime | null
}>()

const time = useTime()
const clipboard = useClipboard()

const json = $computed(() => {
  try {
    return JSON.stringify(value, null, 2) ?? 'null'
  } catch {
    return String(value)
  }
})

const highlighted = $computed(() => highlight(json, 'json'))
</script>

<!-- What a procedure returned, with how long ago it came back and how long it took. -->
<template>
  <div>
    <div class="mb-1 flex items-center gap-1">
      <c-text variant="th">Output</c-text>
      <c-text v-if="receivedAt != null" class="opacity-50" variant="description">
        {{ displayDuration(time.now.diff(receivedAt, 'second'), { short: true }) }} ago
      </c-text>
      <c-text v-if="receivedAt != null && sentAt != null" class="opacity-50" variant="description">
        &middot; {{ displayDuration(receivedAt.diff(sentAt) / 1000, { short: true }) }}
      </c-text>
      <c-tooltip class="ml-auto" :text="clipboard.copied.value ? 'Copied' : 'Copy'">
        <c-button
          color="neutral"
          :icon="clipboard.copied.value ? icons.confirm : icons.copy"
          size="xs"
          variant="ghost"
          @click="clipboard.copy(json)"
        />
      </c-tooltip>
    </div>
    <!-- eslint-disable vue/no-v-html -->
    <!-- prettier-ignore -->
    <pre
      class="border-default bg-elevated/50 m-0 max-h-80 overflow-auto rounded-md border px-2 py-1.5 text-[12px] leading-normal"
    ><code v-html="highlighted" /></pre>
    <!-- eslint-enable vue/no-v-html -->
  </div>
</template>
