<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import type { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

const engine = useEngine()

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
        v-model="widget.query"
        :schema="{
          type: 'string',
          title: 'Video Query',
          enum: possibleQueryNames,
          optional: true,
        }"
      />
      <div class="border-default grid grid-cols-3 rounded-md border text-center">
        <c-schema-form-value
          v-model="widget.autoplay"
          :schema="{ type: 'boolean', title: 'Autoplay' }"
        />
        <c-schema-form-value
          v-model="widget.startMuted"
          :schema="{ type: 'boolean', title: 'Start Muted' }"
          :style="widget.autoplay && { opacity: 0.6 }"
        />
        <c-schema-form-value
          v-model="widget.showControls"
          :schema="{ type: 'boolean', title: 'Show Controls' }"
        />
      </div>
    </div>
  </c-workspace-widget-settings>
</template>
