<script lang="ts" setup>
import { onBeforeUnmount, onMounted } from 'vue'

import { Record } from '@/api/shared'
import { useRecordViewContext } from '@/record-view'

const { record } = defineProps<{
  record: Record
}>()

const context = useRecordViewContext()

const timestamp = $computed(() =>
  record.timestamp.replace('T', ' ').replace('Z', '').replace('+00:00', '')
)

const element = $ref<HTMLElement | null>(null)

onMounted(() => {
  if (element != null) {
    context.register(element)
  }
})

onBeforeUnmount(() => {
  if (element != null) {
    context.unregister(element)
  }
})
</script>

<template>
  <tr
    ref="element"
    :class="[$style.root, 'no-wrap', 'q-tr--no-hover', 'record-view-record']"
    no-hover
  >
    <q-td auto-width>
      <span :class="$style.timestamp">
        {{ timestamp }}
      </span>
    </q-td>
    <q-td auto-width :class="[$style.address, 'monospace-xs']">{{ record.address }}</q-td>
    <slot />
  </tr>
</template>

<style lang="scss" module>
.root {
  height: 24px !important;
  overflow-y: hidden !important;
}

.root :global(.q-td) {
  height: 24px !important;
  padding-top: 0 !important;
  padding-bottom: 2px !important;
  padding-left: 8px !important;
  padding-right: 8px !important;
}

.root:last-child td {
  border-bottom: 1px dashed;
}

:global(.light) .root:last-child td {
  border-bottom-color: rgba(0, 0, 0, 0.12) !important;
}

:global(.dark) .root:last-child td {
  border-bottom-color: rgba(255, 255, 255, 0.12) !important;
}

.timestamp {
  font-family: 'Roboto Mono', monospace;
  font-size: 10px;
  white-space: nowrap;
}

.address {
  min-width: 70px;
}
</style>
