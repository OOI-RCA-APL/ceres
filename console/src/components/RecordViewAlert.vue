<script lang="ts" setup>
import { Alert } from '@/api/alerts'
import RecordViewRecord from '@/components/RecordViewRecord.vue'
import { highlight } from '@/utilities'

const { alert } = $defineProps<{
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

const levelTextColor = $computed(() => {
  switch (alert.level) {
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

const renderedData = $computed(() => highlight(JSON.stringify(alert.data), 'json'))
</script>

<template>
  <record-view-record :record="alert">
    <q-td auto-width :class="$style.levelColumn">
      <q-chip :class="$style.levelChip" :color="levelColor" dense :text-color="levelTextColor">
        <span :class="$style.levelText">
          {{ alert.level }}
        </span>
      </q-chip>
    </q-td>
    <q-td auto-width :class="$style.typeColumn">
      <div :class="$style.type">{{ alert.type }}</div>
    </q-td>
    <q-td>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div :class="$style.data" v-html="renderedData" />
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.levelColumn {
  text-align: center;
  min-width: 56px;
}

.levelChip {
  font-size: 8px;
  font-family: 'Roboto Mono', monospace;
}

.levelText {
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  white-space: nowrap;
  width: 100%;
}

.typeColumn {
  min-width: 52px;
}

.type {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}

.data {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}
</style>
