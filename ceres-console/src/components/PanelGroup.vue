<script lang="ts" setup>
import ResizeHandle from '@/components/ResizeHandle.vue'
import { providePanelGroup } from '@/panel-group'
import { computed } from 'vue'

const { panels, defaultHeight, persist } = defineProps<{
  title: string
  panels?: string[]
  defaultHeight?: number
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
    <div class="full-width no-wrap overflow-scroll relative-position row self-tab-row">
      <slot name="tabs" />
      <q-chip
        class="absolute bg-transparent no-shadow self-title"
        clickable
        dense
        @click="group.toggleAll()"
      >
        {{ title }}
      </q-chip>
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

<style lang="scss" scoped>
.self-tab-row {
  min-height: 32px;
}

.self-title {
  opacity: 0.65;
  top: 2px;
  left: 4px;
}

.self-title:focus-visible {
  outline: 1px solid grey;
}
</style>
