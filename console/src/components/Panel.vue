<script lang="ts" setup>
import AppBoundary from '@/AppBoundary.vue'
import { usePanelGroup } from '@/panel-group'

const { name } = defineProps<{
  name: string
}>()

const group = usePanelGroup()
const isSelected = $computed(() => group.isSelected(name))
</script>

<template>
  <div v-if="isSelected" bordered class="col full-height overflow-hidden" flat square>
    <app-boundary>
      <slot />
    </app-boundary>
  </div>
</template>
