<script lang="ts" setup>
import { Message } from '@/api/models'
import ItemViewItem from '@/components/ItemViewItem.vue'

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
  <item-view-item :item="message">
    <q-td auto-width>
      <q-chip :class="$style.directionChip" :color="directionColor" dense>
        <span :class="$style.directionText">
          {{ message.direction }}
        </span>
      </q-chip>
    </q-td>
    <q-td>
      <span :class="$style.content">
        {{ JSON.stringify(message.content) }}
      </span>
    </q-td>
  </item-view-item>
</template>

<style lang="scss" module>
.directionChip {
  font-size: 9px;
  min-width: 50px;
  text-transform: uppercase;
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
  font-size: 11px;
  white-space: nowrap;
}
</style>
