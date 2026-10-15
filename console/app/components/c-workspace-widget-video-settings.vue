<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import { useWorkspace } from '@/workspace'
import type { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

// The options name each query by its full address, so a stored relative or default address is
// shown by the full one it resolves to, and the option it matches stays selected.
const query = $computed({
  get: () => {
    const at = widget.query?.indexOf('::') ?? -1
    if (widget.query == null || at < 0) {
      return widget.query
    }

    const address = workspace.resolveAddress(widget.query.slice(0, at))
    return address == null ? widget.query : `${address}${widget.query.slice(at)}`
  },
  set: (value: string | null | undefined) => {
    widget.query = value
  },
})

const possibleQueryNames = $computed(() =>
  engine.components.all.flatMap((component) =>
    component.procedures
      .filter(
        (procedure) =>
          procedure.type === 'query' &&
          (procedure.output.type === 'file' || procedure.output.type === 'streaming') &&
          procedure.output.media != null &&
          procedure.output.media.startsWith('video'),
      )
      .map((procedure) => `${component.address}::query::${procedure.name}`),
  ),
)

const transportHints: Record<VideoWidget['transport'], string> = {
  auto: 'WebRTC when it can, HTTP when it cannot.',
  webrtc:
    'Lowest latency. Shows an error rather than switching to HTTP when the network blocks it.',
  http: 'Higher latency, but gets through any network that loads this page.',
}

// A browser only autoplays muted video, so the two settings hold each other to that.
watch(
  () => widget.autoplay,
  () => {
    if (widget.autoplay) {
      widget.startMuted = true
    }
  },
  { immediate: true },
)

watch(
  () => widget.startMuted,
  () => {
    if (!widget.startMuted) {
      widget.autoplay = false
    }
  },
  { immediate: true },
)
</script>

<template>
  <c-workspace-widget-settings :widget>
    <div class="flex flex-col gap-2">
      <c-schema-form-value
        v-model="query"
        :schema="{
          type: 'string',
          title: 'Video Query',
          enum: possibleQueryNames,
          optional: true,
        }"
      />
      <div class="grid grid-cols-2 gap-x-2 gap-y-1 sm:grid-cols-4">
        <c-schema-form-value
          v-model="widget.autoplay"
          align="center"
          :schema="{ type: 'boolean', title: 'Autoplay' }"
          :show-type="false"
        />
        <c-schema-form-value
          v-model="widget.startMuted"
          align="center"
          :schema="{ type: 'boolean', title: 'Start Muted' }"
          :show-type="false"
          :style="widget.autoplay && { opacity: 0.6 }"
        />
        <c-schema-form-value
          v-model="widget.showControls"
          align="center"
          :schema="{ type: 'boolean', title: 'Show Controls' }"
          :show-type="false"
        />
        <c-schema-form-value
          v-model="widget.reconnect"
          align="center"
          :schema="{ type: 'boolean', title: 'Reconnect' }"
          :show-type="false"
        />
      </div>
      <c-schema-form-value
        v-model="widget.transport"
        :schema="{
          type: 'string',
          title: 'Transport',
          description: transportHints[widget.transport],
          enum: ['auto', 'webrtc', 'http'],
        }"
      />
    </div>
  </c-workspace-widget-settings>
</template>
