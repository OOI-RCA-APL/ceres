<template>
  <div v-if="isSelected" class="full-height q-pa-sm">
    <slot />
  </div>
</template>

<script lang="ts" setup>
import { usePanelGroup } from '@/panel-group'

const { name } = defineProps<{
  name: string
}>()

const group = usePanelGroup()
const isSelected = $computed(() => group.isSelected(name))
</script>
