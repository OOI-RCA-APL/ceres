<script lang="ts" setup>
import { useRecordViewContext } from '@/record-view'

const { name } = defineProps<{
  /** The column this cell belongs to, as the view's own column definitions name it. */
  name: string
}>()

// The cell is gone rather than blank when its column is hidden, so nothing has to be bound
// back on to the `<td>` a hidden column would otherwise leave in the row.
defineOptions({ inheritAttrs: false })

const context = useRecordViewContext()
</script>

<template>
  <!-- Exactly one element child, which is what the row's own styles size to pin its height. -->
  <td v-if="context.isColumnVisible(name)" v-bind="$attrs">
    <slot />
  </td>
</template>
