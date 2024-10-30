<script lang="ts" setup>
import { computed } from 'vue'

import ResizeHandle from '@/components/ResizeHandle.vue'
import { providePanelGroup } from '@/panel-group'

const { panels, defaultHeight, persist } = $defineProps<{
  title?: string
  panels?: string[]
  defaultHeight?: number
  minHeight?: number
  maxHeight?: number
  persist?: string
}>()

const group = providePanelGroup(
  computed(() => ({
    panels,
    defaultHeight,
    persist,
  }))
)
</script>

<template>
  <div
    class="column no-wrap"
    :style="group.height != null && group.selected.length ? { height: `${group.height}px` } : ''"
  >
    <div
      :class="[
        $style.tabRow,
        'full-width',
        'no-wrap',
        'overflow-scroll',
        'relative-position',
        'row',
      ]"
    >
      <q-chip
        v-if="title"
        :class="[$style.title, 'absolute', 'bg-transparent', 'no-shadow']"
        clickable
        dense
        @click="group.toggleAll()"
      >
        {{ title }}
      </q-chip>
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
        :max="maxHeight"
        :min="minHeight"
      />
      <q-separator v-else />
    </template>
  </div>
</template>

<style module>
.tabRow {
  min-height: 32px;
}

.title {
  opacity: 0.65;
  top: 2px;
  left: 4px;
  z-index: 1;
}

.title:focus-visible {
  outline: 1px solid grey;
}
</style>
