<script lang="ts" setup>
import ResizeHandle from '@/components/ResizeHandle.vue'
import { usePersisted } from '@/persistence'
import { computed } from 'vue'

const { defaultHeight, persist } = defineProps<{
  defaultHeight: number
  minHeight?: number
  maxHeight?: number
  persist?: string
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
  <div :class="$style.root" :style="{ height: state.height + 'px' }">
    <slot />
    <resize-handle
      v-model="state.height"
      :class="$style.handle"
      direction="vertical"
      :min="minHeight"
      :max="maxHeight"
    />
  </div>
</template>

<style lang="scss" module>
.root {
  position: relative;
}

.handle {
  position: absolute;
  left: 0;
  bottom: 0;
  z-index: 100;
}
</style>
