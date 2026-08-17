<script lang="ts">
/** How tall a record row is, borders and padding included.

The virtual scroller stands in for the rows it is not drawing with exactly this much space, so the
styles below pin a row to it rather than letting its content decide.
*/
export const recordRowHeight = 24
</script>

<script lang="ts" setup>
import { onBeforeUnmount, onMounted } from 'vue'

import type { Record } from '@/api/entity'
import { useRecordViewContext } from '@/record-view'

const { record } = defineProps<{
  record: Record
}>()

const context = useRecordViewContext()

const timestamp = $computed(() =>
  record.timestamp.replace('T', ' ').replace('Z', '').replace('+00:00', ''),
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
  <tr ref="element" :class="[$style.root, 'whitespace-nowrap']">
    <td class="w-0 min-w-22">
      <span class="font-mono text-[10px] whitespace-nowrap">
        {{ timestamp }}
      </span>
    </td>
    <td class="w-0 min-w-16">
      <span class="font-mono text-[10px]">{{ record.address }}</span>
    </td>
    <slot />
  </tr>
</template>

<style module>
.root {
  height: 24px;
  overflow-y: hidden;
}

.root td {
  height: 24px;
  padding: 0 8px 2px;
  border-right: 1px solid var(--ui-border);
  border-top: 1px solid var(--ui-border);
}

/* A cell's own `height` is only a minimum, so the row ends up as tall as its content asks for. Each
cell holds exactly one child, sized here instead, which is what makes `recordRowHeight` true. */
.root td > * {
  display: flex;
  align-items: center;
  height: 21px;
  overflow: hidden;
}

.root td:last-child {
  border-right: none;
}

.root:last-child td {
  border-bottom: 1px dashed var(--ui-border);
}
</style>
