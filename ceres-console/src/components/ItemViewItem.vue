<script lang="ts" setup>
import { Item } from '@/api/models'

const { item } = defineProps<{
  item: Item
}>()
</script>

<template>
  <q-tr class="no-wrap" no-hover>
    <q-td auto-width>
      <span :class="$style.timestamp">
        {{ item.timestamp.format('YYYY-MM-DD HH:mm:ss.SSS') }}
      </span>
    </q-td>
    <q-td auto-width>{{ item.address }}</q-td>
    <slot />
  </q-tr>
</template>

<style lang="scss" module>
.timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  margin-right: 4px;
  white-space: nowrap;
}
</style>
