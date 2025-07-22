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
  <q-menu>
    <q-card bordered>
      <q-list dense>
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
    </q-card>
  </q-menu>
</template>
