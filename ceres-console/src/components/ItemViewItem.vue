<script lang="ts" setup>
import { Item } from '@/api/models'

const { item } = defineProps<{
  item: Item
}>()
</script>

<template>
  <q-tr :class="[$style.root, 'no-wrap', 'item-view-item']" no-hover>
    <q-td auto-width>
      <span :class="$style.timestamp">
        {{ item.timestamp.replace('T', ' ').replace('+00:00', '') }}
      </span>
    </q-td>
    <q-td auto-width class="monospace-sm">{{ item.address }}</q-td>
    <slot />
  </q-tr>
</template>

<style lang="scss" module>
.root {
  height: 31px !important;
  overflow-y: hidden !important;
}

.root:last-child td {
  border-bottom: 1px dashed;
}

:global(.light) .root:last-child td {
  border-bottom-color: rgba(0, 0, 0, 0.12) !important;
}

:global(.dark) .root:last-child td {
  border-bottom-color: rgba(255, 255, 255, 0.12) !important;
}

.timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  margin-right: 4px;
  white-space: nowrap;
}
</style>
