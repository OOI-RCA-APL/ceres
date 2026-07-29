<script lang="ts" setup>
import icons from '@/icons'
import { Widget } from '@/workspace'

defineProps<{ widget: Widget }>()
</script>

<template>
  <div class="column full-height items-center justify-center text-grey-6">
    <q-icon :name="icons.locked" size="24px" />
    <div class="q-mt-sm text-caption">Requires permissions you don't have.</div>
  </div>
</template>
