<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import { useVideoTransports, type VideoTransport } from '@/whep'
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
  auto: 'WebRTC for lowest latency if available in full fidelity, otherwise HTTP.',
  webrtc: 'Lowest latency, not always fully supported.',
  http: 'Higher latency, reliably supported.',
}

const transportLabels: Record<VideoTransport, string> = { webrtc: 'WebRTC', http: 'HTTP' }

// What Automatic chose and why, absent until the widget has settled on one. A forced choice
// needs no line, its hint already says what it does.
const transports = useVideoTransports()
const playing = $computed(() => transports.playing(widget.id))

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
      <c-text
        v-if="widget.transport === 'auto' && playing != null"
        class="italic"
        data-transport-playing
        variant="description"
      >
        Playing over {{ transportLabels[playing.transport] }}. {{ playing.why }}
      </c-text>
    </div>
  </c-workspace-widget-settings>
</template>
