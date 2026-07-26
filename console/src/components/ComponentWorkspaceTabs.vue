<script lang="ts" setup>
import { QPopupEdit } from 'quasar'
import { watch } from 'vue'

import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { isStructurallyEqual } from '@/utilities'
import {
  useWorkspaces,
  Workspace,
  WorkspaceEdit,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
} from '@/workspace'

const { workspaces, active, canManage, activeActions, activeState } = defineProps<{
  workspaces: Workspace[]
  active: string | null
  canManage: boolean
  activeActions?: WorkspaceHeaderActions
  activeState?: WorkspaceHeaderState
}>()

const emit = defineEmits<{ select: [id: string]; create: []; reorder: [workspaces: Workspace[]] }>()

const dialogs = useDialogs()
const workspaceStore = useWorkspaces()

const isApple = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const undoShortcut = isApple ? '⌘Z' : 'Ctrl+Z'
const redoShortcut = isApple ? '⇧⌘Z' : 'Ctrl+Y'

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

// The active tab's working-copy state comes live from its own loaded workspace context, since
// that is authoritative. For every other tab, unsaved changes are detected by comparing each
// workspace's stored edit for the current user against its shared data, fetched once up front
// rather than by loading a full workspace context per tab.
let edits = $ref<Record<string, WorkspaceEdit>>({})

watch(
  () => [active, ...workspaces.map((workspace) => workspace.id)],
  async () => {
    const ids = workspaces.map((workspace) => workspace.id)
    if (ids.length === 0) {
      edits = {}
      return
    }

    const fetched = await workspaceStore.getEdits(ids)
    edits = Object.fromEntries(fetched.map((edit) => [edit.workspace_id, edit]))
  },
  { immediate: true }
)

function hasWorkingCopy(workspace: Workspace): boolean {
  if (workspace.id === active && activeState != null) {
    return activeState.edited
  }

  const edit = edits[workspace.id]
  return edit != null && !isStructurallyEqual(edit.data, workspace.data)
}

// The active tab renames through the live workspace context so the same handler that persists
// the standalone header's rename keeps doing so here. The popup itself lives in this v-for, so
// its template ref comes back as an array rather than a single instance.
let renamePopup = $ref<QPopupEdit[]>([])
let renameDraft = $ref('')

function openRename(workspace: Workspace) {
  renameDraft = workspace.name
  renamePopup[0]?.show()
}

function openSettingsById(workspace: Workspace) {
  dialogs.workspaceSettings(workspace.id).onOk(() => workspaceStore.refresh())
}

function duplicateById(workspace: Workspace) {
  dialogs.duplicateWorkspace(workspace.id, workspace.data)
}

function promptDeleteById(workspace: Workspace) {
  dialogs
    .delete({
      title: 'Delete Workspace',
      html: true,
      message:
        `Are you sure you'd like to delete workspace "${workspace.name}"?\n\n` +
        '<i>' +
        'This action cannot be undone. You and any users with access to this workspace will ' +
        'never see it again.' +
        '</i>',
    })
    .onOk(async () => {
      await workspaceStore.delete(workspace.id)
    })
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
        :name="workspace.id"
        @click="emit('select', workspace.id)"
        @dragend="draggingIndex = null"
        @dragover="onDragOver(index, $event)"
        @dragstart="onDragStart(index, $event)"
        @drop="onDrop(index)"
      >
        <div class="items-center no-wrap row">
          <q-icon :class="$style.tabIcon" :name="icons.workspace" />
          <span :class="$style.label">{{ workspace.name }}</span>
          <q-icon
            v-if="hasWorkingCopy(workspace)"
            :class="$style.workingCopyIcon"
            color="warning"
            :name="icons.workingCopy"
          >
            <q-tooltip>This workspace has unsaved changes.</q-tooltip>
          </q-icon>
          <q-popup-edit
            v-if="workspace.id === active"
            ref="renamePopup"
            v-slot="scope"
            v-model="renameDraft"
            anchor="bottom left"
            auto-save
            :class="$style.popupEdit"
            self="top left"
            :validate="(value: string) => value.trim() !== ''"
            @save="(value: string) => activeActions?.rename(value)"
          >
            <q-card bordered class="q-pa-sm" flat>
              <q-input
                v-model.trim="scope.value"
                autofocus
                dense
                filled
                label="Workspace Name"
                @keyup.enter="scope.set()"
              />
            </q-card>
          </q-popup-edit>
          <q-btn
            class="faded-hover q-ml-xs"
            dense
            flat
            :icon="icons.more"
            round
            size="6px"
            @click.stop
            @mousedown.stop
            @touchstart.stop
          >
            <q-menu anchor="bottom right" :offset="[0, 4]" self="top right">
              <q-card bordered flat>
                <q-list dense>
                  <template
                    v-if="workspace.id === active && activeActions != null && activeState != null"
                  >
                    <q-item v-close-popup clickable dense @click="openRename(workspace)">
                      <q-item-section avatar>
                        <q-icon :name="icons.rename" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Rename</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-close-popup clickable dense @click="activeActions.openSettings()">
                      <q-item-section avatar>
                        <q-icon :name="icons.settings" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Settings</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item
                      clickable
                      dense
                      :disable="!activeState.canUndo"
                      @click="activeActions.undo()"
                    >
                      <q-item-section avatar>
                        <q-icon :name="icons.discard" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Undo</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <span :class="$style.shortcut">{{ undoShortcut }}</span>
                      </q-item-section>
                    </q-item>
                    <q-item
                      clickable
                      dense
                      :disable="!activeState.canRedo"
                      @click="activeActions.redo()"
                    >
                      <q-item-section avatar>
                        <q-icon :class="$style.redoIcon" :name="icons.discard" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Redo</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <span :class="$style.shortcut">{{ redoShortcut }}</span>
                      </q-item-section>
                    </q-item>
                    <q-separator />
                    <q-item v-close-popup clickable dense @click="activeActions.duplicate()">
                      <q-item-section avatar>
                        <q-icon :name="icons.duplicate" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Duplicate</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-close-popup clickable dense @click="activeActions.exportFile()">
                      <q-item-section avatar>
                        <q-icon :name="icons.export" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Export</q-item-label>
                      </q-item-section>
                    </q-item>
                    <template v-if="activeState.canManage">
                      <q-separator />
                      <q-item v-close-popup clickable dense @click="activeActions.promptDelete()">
                        <q-item-section avatar>
                          <q-icon :name="icons.delete" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Delete</q-item-label>
                        </q-item-section>
                      </q-item>
                    </template>
                    <template v-if="activeState.edited">
                      <q-separator />
                      <template v-if="activeState.isViewingOriginal">
                        <q-item v-close-popup clickable dense @click="activeActions.promptRevert()">
                          <q-item-section avatar>
                            <q-icon color="warning" :name="icons.revertToOriginal" />
                          </q-item-section>
                          <q-item-section>
                            <q-item-label>Revert to Original Version</q-item-label>
                          </q-item-section>
                        </q-item>
                        <q-item
                          v-close-popup
                          clickable
                          dense
                          @click="activeActions.stopViewingOriginal()"
                        >
                          <q-item-section avatar>
                            <q-icon :name="icons.close" />
                          </q-item-section>
                          <q-item-section>
                            <q-item-label>Stop Viewing Original</q-item-label>
                          </q-item-section>
                        </q-item>
                      </template>
                      <template v-else>
                        <q-item
                          clickable
                          dense
                          :disable="!activeState.canEdit"
                          @click="activeActions.promptCommit()"
                        >
                          <q-item-section avatar>
                            <q-icon :name="icons.confirm" />
                          </q-item-section>
                          <q-item-section>
                            <q-item-label>Commit Changes</q-item-label>
                          </q-item-section>
                        </q-item>
                        <q-item
                          v-close-popup
                          clickable
                          dense
                          @click="activeActions.startViewingOriginal()"
                        >
                          <q-item-section avatar>
                            <q-icon :name="icons.viewOriginal" />
                          </q-item-section>
                          <q-item-section>
                            <q-item-label>View Original</q-item-label>
                          </q-item-section>
                        </q-item>
                      </template>
                    </template>
                  </template>
                  <template v-else>
                    <q-item v-close-popup clickable dense @click="emit('select', workspace.id)">
                      <q-item-section avatar>
                        <q-icon :name="icons.open" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Open</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-close-popup clickable dense @click="openSettingsById(workspace)">
                      <q-item-section avatar>
                        <q-icon :name="icons.settings" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Settings</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-close-popup clickable dense @click="duplicateById(workspace)">
                      <q-item-section avatar>
                        <q-icon :name="icons.duplicate" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Duplicate</q-item-label>
                      </q-item-section>
                    </q-item>
                    <template v-if="canManage">
                      <q-separator />
                      <q-item v-close-popup clickable dense @click="promptDeleteById(workspace)">
                        <q-item-section avatar>
                          <q-icon :name="icons.delete" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Delete</q-item-label>
                        </q-item-section>
                      </q-item>
                    </template>
                  </template>
                </q-list>
              </q-card>
            </q-menu>
          </q-btn>
        </div>
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
  padding: 0 6px 0 10px;
  border-radius: 13px;
  opacity: 0.7;
  transition: background-color 0.2s, opacity 0.2s;

  &:hover {
    opacity: 1;
  }

  &:global(.q-tab--active) {
    opacity: 1;
    background-color: rgba($primary, 0.18);
    color: $primary;
  }
}

.tabIcon {
  font-size: 15px;
  margin-right: 5px;
}

.label {
  max-width: 160px;
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// Shrunk to a plain icon rather than a full chip, since the tab already carries the workspace's
// name and only needs to flag that local changes exist, not offer a menu of its own.
.workingCopyIcon {
  margin-left: 5px;
  font-size: 12px;
}

.shortcut {
  font-size: 11px;
  opacity: 0.6;
}

// Redo is the undo arrow mirrored, which reads as its opposite without needing a second icon.
.redoIcon {
  transform: scaleX(-1);
}

.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
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
