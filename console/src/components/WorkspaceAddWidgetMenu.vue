<script lang="ts" setup>
import { rootLayoutId, useWorkspace, widgetInfos, WidgetType } from '@/workspace'

const { row, column, layoutId } = defineProps<{
  row: number
  column?: number

  /** Which layout the row and column count against. The workspace's own unless said otherwise. */
  layoutId?: string
}>()

const workspace = useWorkspace()

function add(type: WidgetType) {
  return workspace.addWidget(type, row, column, layoutId ?? rootLayoutId)
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
