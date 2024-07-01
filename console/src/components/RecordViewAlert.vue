<script lang="ts" setup>
import { Alert } from '@/api/alerts'
import RecordViewRecord from '@/components/RecordViewRecord.vue'

const { alert } = defineProps<{
  alert: Alert
}>()

const levelColor = $computed(() => {
  switch (alert.level) {
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
  <record-view-record :record="alert">
    <q-td auto-width>
      <q-chip :class="$style.levelChip" :color="levelColor" dense text-color="black">
        <span :class="$style.levelText">
          {{ alert.level }}
        </span>
      </q-chip>
    </q-td>
    <q-td auto-width>
      <div :class="$style.code">{{ alert.code }}</div>
    </q-td>
    <q-td>
      <div :class="$style.info">{{ JSON.stringify(alert.info) }}</div>
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.levelChip {
  font-size: 9px;
  font-family: 'Roboto Mono', monospace;
}

.levelText {
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  white-space: nowrap;
  width: 100%;
}

.code {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}

.info {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}
</style>
