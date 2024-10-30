<script lang="ts" setup>
import { useWorkspace, widgetInfos, WidgetType } from '@/workspace'

const { row, column } = $defineProps<{
  row: number
  column?: number
}>()

const workspace = useWorkspace()

function add(type: WidgetType) {
  return workspace.addWidget(type, row, column)
}
</script>

<template>
  <q-menu class="no-shadow" :offset="[0, 8]">
    <q-list bordered dense>
      <q-item
        v-for="widget in widgetInfos"
        :key="widget.type"
        v-close-popup
        clickable
        @click="add(widget.type)"
      >
        <q-item-section>
          <q-item-label>{{ widget.name }}</q-item-label>
        </q-item-section>
      </q-item>
    </q-list>
  </q-menu>
</template>
