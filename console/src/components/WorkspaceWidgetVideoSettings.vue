<script lang="ts" setup>
import { watch } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
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
          procedure.output.type === 'media' &&
          procedure.output.media.startsWith('video')
      )
      .map((procedure) => [component.address, procedure.name] as [Address, string])
  )
)

const possibleQueryNames = $computed(() =>
  possibleQueries.map(([address, name]) => `${address}::query::${name}`)
)

watch([() => widget.autoplay, () => widget.startMuted], () => {
  if (widget.autoplay) {
    widget.startMuted = false
  }
})
</script>

<template>
  <div class="q-pb-none q-px-md q-py-md">
    <common-text class="q-mb-sm" variant="title1">{{ widget.name }}</common-text>
    <div class="column">
      <div class="q-mb-sm">
        <schema-form-base
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
            <schema-form-base
              v-model="widget.autoplay"
              :schema="{
                type: 'boolean',
                title: 'Autoplay',
              }"
            />
          </div>
          <div class="col">
            <schema-form-base
              v-model="widget.startMuted"
              :schema="{
                type: 'boolean',
                title: 'Start Muted',
              }"
            />
          </div>
          <div class="col">
            <schema-form-base
              v-model="widget.showControls"
              :schema="{
                type: 'boolean',
                title: 'Controls',
              }"
            />
          </div>
        </q-card>
      </div>
    </div>
  </div>
</template>
