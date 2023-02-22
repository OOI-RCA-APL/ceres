<template>
  <div
    class="column no-wrap"
    :style="group.height != null && group.selected.length ? { height: `${group.height}px` } : ''"
  >
    <div class="no-wrap overflow-scroll relative-position row">
      <template v-if="title">
        <div class="q-px-md q-py-sm self-title">{{ title }}</div>
        <q-separator vertical />
      </template>
      <slot name="tabs" />
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
.self-title {
  opacity: 0.65;
  min-width: 120px;
}
</style>
