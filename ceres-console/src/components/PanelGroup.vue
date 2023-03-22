<template>
  <div
    class="column no-wrap"
    :style="group.height != null && group.selected.length ? { height: `${group.height}px` } : ''"
  >
    <div class="full-width no-wrap overflow-scroll relative-position row self-tab-row">
      <slot name="tabs" />
      <div v-if="title" class="absolute self-title">
        {{ title }}
      </div>
    </div>
    <q-separator />

    <template v-if="group.selected.length">
      <div class="col-grow q-col-gutter-sm q-pa-sm row">
        <slot />
      </div>
      <resize-handle
        v-if="defaultHeight != null && group.height != null"
        v-model="group.height"
        direction="vertical"
        :min="114"
      />
      <q-separator v-else />
    </template>
  </div>
</template>

<script lang="ts" setup>
import ResizeHandle from '@/components/ResizeHandle.vue'
import { providePanelGroup } from '@/panel-group'
import { computed } from 'vue'

const { panels, defaultHeight, persistenceKey } = defineProps<{
  title?: string
  panels?: string[]
  defaultHeight?: number
  persistenceKey?: string
}>()

const group = providePanelGroup(
  computed(() => ({
    panels,
    defaultHeight,
    persistenceKey,
  }))
)
</script>

<style lang="scss" scoped>
.self-tab-row {
  min-height: 32px;
}

.self-title {
  opacity: 0.65;
  top: 6px;
  left: 16px;
}
</style>
