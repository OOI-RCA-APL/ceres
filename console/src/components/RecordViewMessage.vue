<script lang="ts" setup>
import { Message } from '@/api/messages'
import RecordViewRecord from '@/components/RecordViewRecord.vue'
import TextContent from '@/components/TextContent.vue'

const { message } = defineProps<{
  message: Message
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
    <q-td :class="$style.directionColumn">
      <q-chip :class="$style.directionChip" :color="directionColor" dense>
        <span :class="$style.directionText">
          {{ message.direction }}
        </span>
      </q-chip>
    </q-td>
    <q-td>
      <text-content :class="$style.content" :text="message.content" />
    </q-td>
  </record-view-record>
</template>

<style lang="scss" module>
.directionColumn {
  min-width: 76px;
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

.content {
  font-family: 'Roboto Mono', monospace;
  font-size: 9px;
  white-space: nowrap;
}
</style>
