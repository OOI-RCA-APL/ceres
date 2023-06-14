<script lang="ts" setup>
import { LogEntry } from '@/api/models'

import ItemViewItem from '@/components/ItemViewItem.vue'

const { entry } = defineProps<{
  entry: LogEntry
}>()

const levelColor = $computed(() => {
  switch (entry.level) {
    case 'debug':
      return 'grey'
    case 'info':
      return 'info'
    case 'warning':
      return 'warning'
    case 'error':
      return 'negative'
    case 'critical':
      return 'negative'
  }
})
</script>

<template>
  <item-view-item :item="entry">
    <q-td>
      <q-chip :class="$style.levelChip" :color="levelColor" dense text-color="black">
        <span :class="$style.levelText">
          {{ entry.level }}
        </span>
      </q-chip>
    </q-td>
    <q-td class="col-grow">
      <span :class="$style.content">
        {{ JSON.stringify(entry.content) }}
      </span>
    </q-td>
  </item-view-item>
</template>

<style lang="scss" module>
.levelChip {
  font-size: 9px;
  min-width: 58px;
  text-transform: uppercase;
}

.levelText {
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  width: 100%;
}

.content {
  font-family: 'Roboto Mono', monospace;
  font-size: 11px;
  white-space: nowrap;
}
</style>
