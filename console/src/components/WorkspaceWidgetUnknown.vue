<script lang="ts" setup>
import icons from '@/icons'
import { Widget } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
}>()
</script>

<template>
  <div class="column flex-center q-gutter-xs q-pa-md text-center" :class="$style.root">
    <q-icon :name="icons.help" size="24px" />
    <div>Unknown Widget</div>
    <div :class="$style.note">
      This widget of type "{{ widget.type }}" is unsupported by the current Ceres version.
    </div>
  </div>
</template>

<style lang="scss" module>
.root {
  opacity: 0.7;
}

.note {
  font-size: 12px;
  opacity: 0.7;
}
</style>
