<script lang="ts" setup>
import icons from '@/icons'
import { Workspace } from '@/workspace'

const { workspaces, active, canManage } = defineProps<{
  workspaces: Workspace[]
  active: string | null
  canManage: boolean
}>()

const emit = defineEmits<{ select: [id: string]; create: []; reorder: [workspaces: Workspace[]] }>()

// Tabs are dragged to reorder them. Only the index being dragged is tracked, the drop target is
// read from the tab the pointer is over.
let draggingIndex = $ref<number | null>(null)

function onDragStart(index: number, event: DragEvent) {
  draggingIndex = index
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer != null) {
    event.dataTransfer.effectAllowed = 'move'
  }
}

function onDragOver(index: number, event: DragEvent) {
  if (draggingIndex == null || draggingIndex === index) {
    return
  }

  event.preventDefault()
  if (event.dataTransfer != null) {
    event.dataTransfer.dropEffect = 'move'
  }
}

function onDrop(index: number) {
  if (draggingIndex == null || draggingIndex === index) {
    draggingIndex = null
    return
  }

  const reordered = [...workspaces]
  const [moved] = reordered.splice(draggingIndex, 1)
  reordered.splice(index, 0, moved)
  draggingIndex = null
  emit('reorder', reordered)
}
</script>

<template>
  <div class="items-center no-wrap row">
    <q-tabs
      :class="$style.tabs"
      dense
      indicator-color="transparent"
      inline-label
      :model-value="active"
      no-caps
      shrink
    >
      <q-tab
        v-for="(workspace, index) in workspaces"
        :key="workspace.id"
        :class="[$style.tab, draggingIndex === index && $style.dragging]"
        draggable="true"
        :icon="icons.workspace"
        :label="workspace.name"
        :name="workspace.id"
        @click="emit('select', workspace.id)"
        @dragend="draggingIndex = null"
        @dragover="onDragOver(index, $event)"
        @dragstart="onDragStart(index, $event)"
        @drop="onDrop(index)"
      >
        <q-tooltip>Workspace "{{ workspace.name }}", drag to reorder.</q-tooltip>
      </q-tab>
    </q-tabs>
    <q-btn
      v-if="canManage"
      :class="[$style.add, 'q-ml-xs']"
      dense
      flat
      :icon="icons.add"
      round
      size="sm"
      @click="emit('create')"
    >
      <q-tooltip>Add a workspace for this component.</q-tooltip>
    </q-btn>
  </div>
</template>

<style lang="scss" module>
// Each tab carries the workspace icon so the group reads as workspaces rather than as page
// sections, and the selected one is marked by a filled pill instead of an underline, which sits
// better in a header rail that already uses chips and icon buttons.
.tabs {
  height: 30px;
}

.tab {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 13px;
  opacity: 0.7;
  transition: background-color 0.2s, opacity 0.2s;

  &:hover {
    opacity: 1;
  }

  :global(.q-tab__icon) {
    font-size: 15px;
    margin-right: 5px;
  }

  :global(.q-tab__label) {
    font-size: 13px;
  }

  &:global(.q-tab--active) {
    opacity: 1;
    background-color: rgba($primary, 0.18);
    color: $primary;
  }
}

.dragging {
  opacity: 0.4;
}

.add {
  opacity: 0.7;

  &:hover {
    opacity: 1;
  }
}
</style>
