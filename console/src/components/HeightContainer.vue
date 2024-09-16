<script lang="ts" setup>
import { computed } from 'vue'

import ResizeHandle from '@/components/ResizeHandle.vue'
import { KeyInput, usePersisted } from '@/persistence'

const { defaultHeight, persist } = defineProps<{
  defaultHeight: number
  minHeight?: number
  maxHeight?: number
  persist?: KeyInput
  scroll?: boolean
}>()

const state = usePersisted({
  schema: ({ object, number }) =>
    object({
      height: number().default(defaultHeight),
    }),
  methods: computed(() => (persist ? [{ type: 'local-storage', key: persist }] : [])),
})
</script>

<template>
  <div :class="[$style.root, scroll && $style.scroll]" :style="{ height: state.height + 'px' }">
    <slot />
    <resize-handle
      v-model="state.height"
      :class="$style.handle"
      direction="vertical"
      :max="maxHeight"
      :min="minHeight"
    />
  </div>
</template>

<style lang="scss" module>
.root {
  position: relative;
}

.scroll {
  overflow-y: auto;
}

.handle {
  position: absolute;
  left: 0;
  bottom: 0;
  z-index: 100;
}
</style>
