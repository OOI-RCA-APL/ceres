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
    <td class="w-0 min-w-20">
      <span class="font-mono text-[10px] whitespace-nowrap">
        {{ message.connection ?? '' }}
      </span>
    </td>
    <td class="w-0 min-w-17">
      <div class="justify-center">
        <c-badge
          :color="directionColor"
          :ui="{ base: 'font-mono text-[8px] px-1.5 py-0 min-w-9.5 justify-center rounded-full' }"
          variant="solid"
        >
          {{ message.direction }}
        </c-badge>
      </div>
    </td>
    <td>
      <c-data-content
        class="font-mono text-[9px] whitespace-nowrap"
        :data="message.data"
        :display="dataDisplay"
      />
    </td>
  </c-record-view-record>
</template>
