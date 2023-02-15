<template>
  <div
    class="column"
    :style="group.height != null && group.selected.length ? { height: `${group.height}px` } : ''"
  >
    <div class="col-shrink relative-position row">
      <template v-if="title">
        <div class="q-px-md q-py-sm text-grey-8" style="min-width: 120px">{{ title }}</div>
        <q-separator vertical />
      </template>
      <slot name="tabs" />
    </div>
    <q-separator />

    <template v-if="group.selected.length">
      <div class="col-grow row">
        <div class="col">
          <slot />
        </div>
      </div>
      <resize-handle v-if="defaultHeight != null" vertical @resize="onResize" />
      <q-separator v-else />
    </template>
  </div>
</template>

<script lang="ts" setup>
import ResizeHandle from '@/components/ResizeHandle.vue'
import { providePanelGroup } from '@/panel-group'
import { computed } from 'vue'

const minHeight = 114

const { defaultHeight, persistenceKey } = defineProps<{
  title?: string
  defaultHeight?: number
  persistenceKey?: string
}>()

const group = providePanelGroup(
  computed(() => ({
    defaultHeight,
    persistenceKey,
  }))
)

function onResize(delta: number) {
  if (group.height != null) {
    group.height = Math.max(group.height + delta, minHeight)
  }
}

onResize(0)
</script>
