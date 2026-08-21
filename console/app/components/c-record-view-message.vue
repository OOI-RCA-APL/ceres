<script lang="ts" setup>
import type { Message } from '@/api/messages'
import type { DataContentDisplay } from '@/components/c-data-content.vue'

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
  <c-record-view-record :record="message">
    <c-record-view-connection :address="message.address" :name="message.connection" />
    <c-record-view-cell class="w-0 min-w-17" name="direction">
      <div class="justify-center">
        <c-badge
          :color="directionColor"
          :ui="{ base: 'font-mono text-[8px] px-1.5 py-0 min-w-9.5 justify-center rounded-full' }"
          variant="solid"
        >
          {{ message.direction }}
        </c-badge>
      </div>
    </c-record-view-cell>
    <c-record-view-cell name="data">
      <c-data-content
        class="font-mono text-[9px] whitespace-nowrap"
        :data="message.data"
        :display="dataDisplay"
      />
    </c-record-view-cell>
  </c-record-view-record>
</template>
