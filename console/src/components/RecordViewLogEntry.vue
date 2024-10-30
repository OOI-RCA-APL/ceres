<script lang="ts" setup>
import { LogEntry } from '@/api/log-entries'
import RecordViewRecord from '@/components/RecordViewRecord.vue'
import TextContent from '@/components/TextContent.vue'

const { entry } = $defineProps<{
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

const levelTextColor = $computed(() => {
  switch (entry.level) {
    case 'debug':
      return 'black'
    case 'info':
      return 'black'
    case 'warning':
      return 'black'
    case 'error':
      return 'white'
    case 'critical':
      return 'white'
  }
})
</script>

<template>
  <record-view-record :record="entry">
    <q-td auto-width :class="$style.levelColumn">
      <q-chip :class="$style.levelChip" :color="levelColor" dense :text-color="levelTextColor">
        <span :class="$style.levelText">
          {{ entry.level }}
        </span>
      </q-chip>
    </q-td>
    <q-td>
      <text-content :class="$style.content" :text="entry.content" />
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.levelColumn {
  text-align: center;
}

.levelChip {
  font-size: 8px;
  font-family: 'Roboto Mono', monospace;
}

.levelText {
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  width: 100%;
}

.content {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
  width: 100%;
}
</style>
