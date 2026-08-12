<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { getWidgetInfo, Widget } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
}>()

// An unnamed widget titles its dialog with the kind's own name.
const title = $computed(() => (widget.name !== '' ? widget.name : getWidgetInfo(widget.type).name))
</script>

<template>
  <div class="q-pa-md">
    <common-text class="q-mb-sm" variant="title1">{{ title }}</common-text>
    <slot />
  </div>
</template>
