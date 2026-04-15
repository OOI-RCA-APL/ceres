<script lang="ts" setup>
import { Message } from '@/api/messages'
import DataContent from '@/components/DataContent.vue'
import type { DataContentDisplay } from '@/components/DataContent.vue'
import RecordViewRecord from '@/components/RecordViewRecord.vue'

const { message, dataDisplay = 'default' } = defineProps<{
  message: Message
  dataDisplay?: DataContentDisplay
}>()

const directionColor = $computed(() => {
  switch (message.direction) {
    case 'receive':
      return 'info'
    case 'send':
      return 'warning'
  }
})
</script>

<template>
  <record-view-record :record="message">
    <q-td auto-width :class="$style.connectionColumn">
      <span :class="$style.connection"> {{ message.connection ?? '' }} </span>
    </q-td>
    <q-td :class="$style.directionColumn">
      <q-chip :class="$style.directionChip" :color="directionColor" dense>
        <span :class="$style.directionText">{{ message.direction }}</span>
      </q-chip>
    </q-td>
    <q-td>
      <data-content :class="$style.data" :data="message.data" :display="dataDisplay" />
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.connectionColumn {
  min-width: 80px;
}

.connection {
  font-family: 'Roboto Mono', monospace;
  font-size: 10px;
  white-space: nowrap;
}

.directionColumn {
  min-width: 68px;
  text-align: center;
}

.directionChip {
  font-size: 8px;
  min-width: 38px;
  font-family: 'Roboto Mono', monospace;
}

.directionText {
  color: black;
  justify-items: center;
  text-align: center;
  white-space: nowrap;
  width: 100%;
}

.data {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}
</style>
