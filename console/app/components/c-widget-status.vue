<script lang="ts" setup>
import type { WidgetStatus } from '@/widget-status'

const { status } = defineProps<{
  status: WidgetStatus
}>()
</script>

<template>
  <span class="flex items-center gap-1 text-[10px]">
    <!-- Muted like the rest of the header, so a wall of videos stays calm. The dot is filled at
    the newest frame and hollow once paused or lagging, when a click brings it back. -->
    <button
      v-if="status.live != null"
      :class="[
        'text-muted flex items-center gap-1',
        status.live === 'live' ? 'cursor-default opacity-70' : 'opacity-40 hover:opacity-100',
      ]"
      :data-live-state="status.live"
      data-widget-live
      :disabled="status.live === 'live'"
      :title="status.live === 'behind' ? 'Go to live' : undefined"
      type="button"
      @click.prevent.stop="status.goLive?.()"
      @mousedown.stop
      @touchstart.stop
    >
      <span
        :class="[
          'size-1.5 rounded-full border border-current',
          status.live === 'live' && 'bg-current',
        ]"
      />
      Live
    </button>
    <span v-if="status.live != null" class="text-muted opacity-70">·</span>
    <button
      v-if="status.cycle != null"
      class="text-muted opacity-70 hover:opacity-100"
      data-widget-status
      type="button"
      @click.prevent.stop="status.cycle()"
      @mousedown.stop
      @touchstart.stop
    >
      {{ status.text }}
    </button>
    <span v-else class="text-muted opacity-70" data-widget-status>
      {{ status.text }}
    </span>
  </span>
</template>
