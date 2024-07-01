<script lang="ts" setup>
import { Item } from '@/api/shared'

const { record } = defineProps<{
  record: Item
}>()

const timestamp = $computed(() =>
  record.timestamp.replace('T', ' ').replace('Z', '').replace('+00:00', '')
)
</script>

<template>
  <q-tr :class="[$style.root, 'no-wrap', 'record-view-record']" no-hover>
    <q-td auto-width>
      <span :class="$style.timestamp">
        {{ timestamp }}
      </span>
    </q-td>
    <q-td auto-width class="monospace-xs">{{ record.address }}</q-td>
    <slot />
  </q-tr>
</template>

<style lang="scss" module>
.root {
  height: 24px !important;
  overflow-y: hidden !important;
}

.root :global(.q-td) {
  height: 24px !important;
  padding-top: 0 !important;
  padding-bottom: 2px !important;
  padding-left: 8px !important;
  padding-right: 8px !important;
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
  font-size: 10px;
  white-space: nowrap;
}
</style>
