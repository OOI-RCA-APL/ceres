<script lang="ts" setup>
import { watch } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import WorkspaceWidgetSettings from '@/components/WorkspaceWidgetSettings.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import type { VideoWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: VideoWidget
}>()

const engine = useEngine()

const possibleQueries = $computed(() =>
  engine.components.all.flatMap((component) =>
    component.procedures
      .filter(
        (procedure) =>
          procedure.type === 'query' &&
          (procedure.output.type === 'file' || procedure.output.type === 'streaming') &&
          procedure.output.media != null &&
          procedure.output.media.startsWith('video')
      )
      .map((procedure) => [component.address, procedure.name] as [Address, string])
  )
)

const possibleQueryNames = $computed(() =>
  possibleQueries.map(([address, name]) => `${address}::query::${name}`)
)

watch(
  [() => widget.autoplay],
  () => {
    if (widget.autoplay) {
      widget.startMuted = true
    }
  },
  { immediate: true }
)
watch(
  [() => widget.startMuted],
  () => {
    if (!widget.startMuted) {
      widget.autoplay = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <workspace-widget-settings :widget>
    <div class="column">
      <div class="q-mb-sm">
        <schema-form-value
          v-model="widget.query"
          :schema="{
            type: 'string',
            title: 'Video Query',
            enum: possibleQueryNames,
            optional: true,
          }"
        />
      </div>
      <div>
        <q-card bordered class="justify-between q-pa-none row text-center" flat>
          <div class="col">
            <schema-form-value
              v-model="widget.autoplay"
              :schema="{
                type: 'boolean',
                title: 'Autoplay',
              }"
            />
          </div>
          <div class="col">
            <schema-form-value
              v-model="widget.startMuted"
              :schema="{
                type: 'boolean',
                title: 'Start Muted',
              }"
              :style="widget.autoplay && { opacity: 0.6 }"
            />
          </div>
          <div class="col">
            <schema-form-value
              v-model="widget.showControls"
              :schema="{
                type: 'boolean',
                title: 'Show Controls',
              }"
            />
          </div>
        </q-card>
      </div>
    </div>
  </workspace-widget-settings>
</template>
