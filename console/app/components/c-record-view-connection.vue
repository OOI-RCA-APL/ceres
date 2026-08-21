<script lang="ts" setup>
import type { Address } from '@/api/address'
import { useEngine } from '@/api/engine'

const { address, name } = defineProps<{
  address: Address
  /** The connection the record was stored under, absent for one no connection produced. */
  name: string | null
}>()

const engine = useEngine()

// Looked up by address as well as by name, a connection name being unique only within its own
// component while a pane scoped to a subtree draws records from several.
const connection = $computed(() =>
  name == null ? null : engine.components.getConnection(address, name),
)
</script>

<template>
  <c-record-view-cell class="w-0 min-w-20" name="connection">
    <c-tooltip
      v-if="connection != null"
      :ui="{ content: 'h-auto flex-col items-start gap-0.5 py-1.5' }"
    >
      <span class="font-mono text-[10px] whitespace-nowrap">{{ connection.name }}</span>
      <template #content>
        <c-text v-if="connection.label" variant="body3">{{ connection.label }}</c-text>
        <c-text variant="description">{{ connection.uri }}</c-text>
      </template>
    </c-tooltip>
    <span v-else class="font-mono text-[10px] whitespace-nowrap">{{ name ?? '' }}</span>
  </c-record-view-cell>
</template>
