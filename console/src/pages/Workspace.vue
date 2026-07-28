<script lang="ts" setup>
import { useEventListener, useMouse, useResizeObserver } from '@vueuse/core'
import { QPopupEdit, colors } from 'quasar'
import { computed, onMounted, reactive, watchEffect, watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import FullPage from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceGap from '@/components/WorkspaceGap.vue'
import WorkspaceWidget from '@/components/WorkspaceWidget.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError } from '@/errors'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { deepClone } from '@/utilities'
import {
  provideWorkspace,
  resolveWidgetWidths,
  widgetWidthSubdivisions,
  Widget,
  WorkspaceData,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
  getWidgetInfo,
} from '@/workspace'

const { id } = defineProps<{
  id: string
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()

const workspace = provideWorkspace(computed(() => id))
await workspace.load()

const layout = $ref<HTMLDivElement | null>(null)
let original = $ref<WorkspaceData | null>(null)
let isViewingOriginal = $computed(() => original != null)

if (workspace.data == null || workspace.name == null) {
  throw new NotFoundError('workspace', id)
}

async function startViewingOriginal() {
  await workspace.refresh()
  original = deepClone(workspace.originalData) as WorkspaceData
  key++
}

function stopViewingOriginal() {
  original = null
  key++
}

const data = $computed(() => {
  if (isViewingOriginal) {
    return original
  } else {
    return workspace.data
  }
})

let key = $ref(0)

let name = $ref<string>(workspace.name)
watch(
  () => name,
  async () => {
    // Switching workspaces reseeds this from the newly loaded one, which must not be mistaken
    // for the user having renamed anything.
    if (name === workspace.name) {
      return
    }

    await workspace.rename(name)
  }
)
watch(
  () => workspace.name,
  () => {
    if (workspace.name != null) {
      name = workspace.name
    }
  }
)
let renamePopup = $ref<QPopupEdit | null>(null)
let layoutWidth = $ref<number | null>(null)

useEventListener(window, 'mouseup', () => {
  workspace.drag = null
})

const isApple = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const undoShortcut = isApple ? '⌘Z' : 'Ctrl+Z'
const redoShortcut = isApple ? '⇧⌘Z' : 'Ctrl+Y'

// Undo and redo on the usual shortcuts, skipped while the user is typing so a text field keeps
// its own history. Redo accepts both spellings, since editors are split between them.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (!(event.metaKey || event.ctrlKey) || event.altKey) {
    return
  }

  const target = event.target as HTMLElement | null
  if (target?.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target?.tagName ?? '')) {
    return
  }

  const key = event.key.toLowerCase()
  if (key === 'z' && !event.shiftKey) {
    event.preventDefault()
    workspace.undo()
  } else if ((key === 'z' && event.shiftKey) || key === 'y') {
    event.preventDefault()
    workspace.redo()
  }
})

useResizeObserver($$(layout), (resizes) => {
  for (const resize of resizes) {
    layoutWidth = resize.contentRect.width
  }
})

watchEffect(() => {
  if (workspace.drag != null) {
    document.body.style.cursor = 'grabbing'
  } else {
    document.body.style.cursor = 'unset'
  }
})

const mouse = reactive(useMouse({ type: 'client' }))
const draggedWidgetIconStyle = $computed(() => ({
  left: `${mouse.x}px`,
  top: `${mouse.y}px`,
  transform: 'translate(-50%, -50%)',
}))

function duplicate() {
  dialogs.duplicateWorkspace(id, data as WorkspaceData)
}

function exportFile() {
  workspace.exportFile()
}

function openSettings() {
  dialogs.workspaceSettings(id).onOk(() => workspace.refresh())
}

function promptDelete() {
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
      const scope = workspace.scope
      await workspace.delete()

      // A component-placed workspace is hosted by that component's page, so deleting it
      // returns there with no workspace selected rather than leaving the component entirely.
      if (scope != null && !scope.isEngine) {
        await navigation.replace(`/components/${scope}`)
      } else {
        await navigation.go('/')
      }
    })
}

function promptCommit() {
  dialogs
    .confirm({
      title: 'Commit Changes',
      html: true,
      message:
        `Commit changes to workspace "${workspace.name}"?\n\n` +
        '<i>' +
        'This will update the current shared version of this workspace, allowing users with ' +
        'access to see this version.' +
        '</i>',
      ok: {
        label: 'Commit',
        color: 'primary',
      },
    })
    .onOk(async () => {
      await workspace.save()
      notify.success('Workspace changes committed successfully.')
    })
}

function promptRevert() {
  dialogs
    .confirm({
      title: 'Revert Changes',
      html: true,
      message:
        `Revert all personal changes to this workspace?\n\n` +
        '<i>' +
        'This will discard your current working copy and replace it with the latest shared ' +
        'version of the workspace. The workspace will not be modified for any other users.' +
        '</i>',
      ok: {
        label: 'Yes',
        color: 'warning',
      },
    })
    .onOk(async () => {
      await workspace.revert()
      original = null
      key++
    })
}

function resolveAllWidgetWidths() {
  if (data == null) {
    return
  }

  for (const row of data.layout) {
    resolveWidgetWidths(row.widgets)
  }
}

function getWidgetWidthStyle(widget: Widget) {
  if (layoutWidth == null) {
    return undefined
  }

  const width = `${Math.round((widget.width / widgetWidthSubdivisions) * layoutWidth).toFixed(1)}px`

  return {
    maxWidth: width,
    minWidth: width,
  }
}

onMounted(() => {
  resolveAllWidgetWidths()
})

// Exposed through the `header-prepend` slot so a scoped workspace's tab strip can drive these
// same handlers instead of the built-in header, which that slot replaces.
const headerActions: WorkspaceHeaderActions = {
  rename: (value) => {
    name = value
  },
  openSettings,
  undo: () => workspace.undo(),
  redo: () => workspace.redo(),
  duplicate,
  exportFile,
  promptDelete,
  promptCommit,
  promptRevert,
  startViewingOriginal,
  stopViewingOriginal,
}

const headerState = $computed<WorkspaceHeaderState>(() => ({
  edited: workspace.edited,
  canManage: workspace.canManage,
  canEdit: workspace.canEdit,
  canUndo: workspace.canUndo,
  canRedo: workspace.canRedo,
  isViewingOriginal,
}))
</script>

<template>
  <full-page :class="$style.root" :dense="$slots['header-prepend'] != null">
    <div
      v-if="workspace.drag != null"
      key="dragged-widget-icon"
      :class="$style.draggedWidgetIcon"
      :style="draggedWidgetIconStyle"
    >
      <q-card bordered class="q-px-xs" flat>
        <common-text variant="th">
          {{ workspace.drag.widget.name }}
        </common-text>
      </q-card>
    </div>
    <template #header-append>
      <slot :actions="headerActions" name="header-prepend" :state="headerState" />
      <template v-if="!$slots['header-prepend']">
        <div @dblclick="renamePopup?.show()">
          <common-text
            class="q-ml-md q-mr-sm"
            :class="workspace.canManage && $style.nameEditable"
            variant="title2"
          >
            {{ name }}
          </common-text>
          <q-popup-edit
            v-if="workspace.canManage && workspace.data != null"
            ref="renamePopup"
            v-slot="scope"
            v-model="name"
            anchor="bottom left"
            auto-save
            :class="$style.popupEdit"
            :cover="false"
            no-parent-event
            self="top left"
            :validate="(value: string) => value.trim() !== ''"
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
        </div>
        <q-btn
          v-if="workspace.data != null"
          class="faded-hover q-ml-xs"
          flat
          :icon="icons.more"
          round
          size="8px"
        >
          <q-menu anchor="top right" :offset="[8, 5]" self="top left">
            <q-card bordered>
              <q-list dense>
                <q-item v-close-popup clickable dense @click="openSettings">
                  <q-item-section avatar>
                    <q-icon :name="icons.settings" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Settings</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item clickable dense :disable="!workspace.canUndo" @click="workspace.undo()">
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
                <q-item clickable dense :disable="!workspace.canRedo" @click="workspace.redo()">
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
                <q-item clickable dense>
                  <q-item-section avatar>
                    <q-icon :name="icons.add" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Add Widget</q-item-label>
                  </q-item-section>
                  <workspace-add-widget-menu
                    anchor="top right"
                    :offset="[8, 0]"
                    :row="-1"
                    self="top left"
                  />
                  <q-item-section side>
                    <q-icon :name="icons.menuRight" size="16px" />
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item v-close-popup clickable dense @click="duplicate">
                  <q-item-section avatar>
                    <q-icon :name="icons.duplicate" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Duplicate</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-close-popup clickable dense @click="exportFile">
                  <q-item-section avatar>
                    <q-icon :name="icons.export" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Export</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item
                  v-if="workspace.canManage"
                  v-close-popup
                  clickable
                  dense
                  @click="promptDelete"
                >
                  <q-item-section avatar>
                    <q-icon :name="icons.delete" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Delete</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </q-menu>
        </q-btn>
        <q-space />
        <div class="q-mr-md">
          <q-btn
            v-if="workspace.edited && isViewingOriginal"
            class="q-mr-sm"
            clickable
            color="warning"
            dense
            flat
            :icon="icons.revertToOriginal"
            label="Revert to Original Version"
            style="padding-top: 2px; padding-bottom: 2px"
            @click="promptRevert"
          />
          <q-btn
            v-if="workspace.edited && isViewingOriginal"
            clickable
            dense
            :icon="icons.close"
            round
            size="12px"
            unelevated
            @click="stopViewingOriginal"
          />
          <q-chip
            v-else-if="workspace.edited"
            class="q-px-sm"
            clickable
            color="warning"
            dense
            :icon="icons.workingCopy"
            label="Working Copy"
            size="12px"
            text-color="white"
          >
            <q-icon class="q-ml-xs" :name="icons.menuDown" />
            <q-menu :offset="[0, 10]">
              <q-card bordered>
                <q-list dense>
                  <q-item clickable :disable="!workspace.canEdit" @click="promptCommit">
                    <q-item-section avatar>
                      <q-icon :name="icons.confirm" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Commit Changes</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item clickable @click="startViewingOriginal">
                    <q-item-section avatar>
                      <q-icon :name="icons.viewOriginal" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>View Original</q-item-label>
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-card>
            </q-menu>
          </q-chip>
        </div>
      </template>
    </template>
    <div
      :key="key"
      class="q-px-sm"
      :style="isViewingOriginal && { border: `1px dashed ${colors.getPaletteColor('warning')}` }"
    >
      <div v-if="workspace.loading" ref="layout" class="q-py-lg" />
      <div v-else-if="data == null" ref="layout" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists.</div>
      </div>
      <div v-else ref="layout">
        <div
          v-for="(row, i) in data.layout"
          :key="row.id"
          class="full-width no-wrap q-my-sm relative-position row"
          :style="{
            height: row.collapsed ? undefined : `${row.height}px`,
          }"
        >
          <workspace-gap
            v-if="workspace.drag != null"
            :class="$style.gapVerticalTop"
            direction="vertical"
            :row="i"
          />
          <workspace-gap
            v-if="workspace.drag != null && i === data.layout.length - 1"
            v-show="workspace.drag != null"
            :class="$style.gapVerticalBottom"
            direction="vertical"
            :row="i + 1"
          />
          <resize-handle
            v-if="workspace.drag == null && !row.collapsed"
            v-model="row.height"
            :class="$style.verticalResizeHandle"
            direction="vertical"
            :min="
              Math.max(
                ...row.widgets.map((widget) => getWidgetInfo(widget.type).options.minHeight ?? 50),
                50
              )
            "
            :step="5"
            visibility="hover"
          />
          <div
            v-for="(widget, j) in row.widgets"
            :key="widget.id"
            :class="[
              j < row.widgets.length - 1 ? 'col-shrink' : 'col-grow',
              'relative-position',
              row.widgets.length === 1
                ? ''
                : j === 0
                ? 'q-pr-xs'
                : j === row.widgets.length - 1
                ? 'q-pl-xs'
                : 'q-px-xs',
            ]"
            :style="j < row.widgets.length - 1 ? getWidgetWidthStyle(widget) : undefined"
          >
            <template v-if="workspace.drag != null">
              <workspace-gap
                v-if="j === 0"
                :class="$style.gapHorizontalLeft"
                :column="j"
                direction="horizontal"
                :row="i"
              />
              <workspace-gap
                v-else
                :class="$style.gapHorizontalMiddle"
                :column="j - 1"
                direction="horizontal"
                :row="i"
              />
              <workspace-gap
                v-if="workspace.drag != null && j === row.widgets.length - 1"
                :class="$style.gapHorizontalRight"
                :column="j + 1"
                direction="horizontal"
                :row="i"
              />
            </template>
            <resize-handle
              v-if="layoutWidth && workspace.drag == null && j < row.widgets.length - 1"
              :class="$style.horizontalResizeHandle"
              direction="horizontal"
              :min="100"
              :model-value="(widget.width / widgetWidthSubdivisions) * layoutWidth"
              :step="1 / widgetWidthSubdivisions"
              visibility="hover"
              @update:model-value="
                (pixels) => {
                  if (layoutWidth == null) {
                    return
                  }

                  widget.width = Math.round((pixels / layoutWidth) * widgetWidthSubdivisions)
                  resolveWidgetWidths(row.widgets, j, 'after')
                }
              "
            />
            <workspace-widget
              :class="workspace.drag?.widget === widget && $style.draggedWidget"
              :column="j"
              :container="row"
              :row="i"
              :widget="widget"
            />
          </div>
        </div>
      </div>
    </div>
    <!-- The whole row is the target rather than just the dot, since the dot is small and the row
    already lights up on hover, which promises a click the dot alone would not accept. -->
    <div
      v-if="!isViewingOriginal && data != null"
      class="row"
      :class="[$style.addWidgetRow, 'faded-hover', 'items-center', 'justify-center', 'q-mt-sm']"
    >
      <q-btn color="primary" :icon="icons.add" round size="8px" tabindex="-1" unelevated />
      <q-tooltip class="bg-primary">Add Widget</q-tooltip>
      <workspace-add-widget-menu
        anchor="bottom middle"
        :offset="[0, 8]"
        :row="data.layout.length"
        self="top middle"
      />
    </div>
    <div :class="$style.bottomPadding" />
    <!-- A working copy is normally an ongoing personal state rather than a staging area, so the
    bar reads as neutral status. It appears only while one exists, and the same actions stay in the
    tab's menu, since this is a shortcut rather than the only route to them. -->
    <div v-if="workspace.edited" :class="[$style.actionBar, 'items-center', 'q-gutter-xs', 'row']">
      <q-btn
        v-if="!isViewingOriginal"
        dense
        :disable="!workspace.canUndo"
        flat
        :icon="icons.discard"
        round
        size="sm"
        @click="workspace.undo()"
      >
        <q-tooltip>Undo ({{ undoShortcut }})</q-tooltip>
      </q-btn>
      <q-btn
        v-if="!isViewingOriginal"
        :class="$style.redoButton"
        dense
        :disable="!workspace.canRedo"
        flat
        :icon="icons.discard"
        round
        size="sm"
        @click="workspace.redo()"
      >
        <q-tooltip>Redo ({{ redoShortcut }})</q-tooltip>
      </q-btn>
      <q-separator v-if="!isViewingOriginal" vertical />
      <template v-if="isViewingOriginal">
        <q-btn
          color="warning"
          dense
          flat
          :icon="icons.revertToOriginal"
          round
          size="sm"
          @click="promptRevert()"
        >
          <q-tooltip>Revert to Original Version</q-tooltip>
        </q-btn>
        <q-btn dense flat :icon="icons.close" round size="sm" @click="stopViewingOriginal()">
          <q-tooltip>Stop Viewing Original</q-tooltip>
        </q-btn>
      </template>
      <template v-else>
        <q-btn
          dense
          flat
          :icon="icons.viewOriginal"
          round
          size="sm"
          @click="startViewingOriginal()"
        >
          <q-tooltip>View Original</q-tooltip>
        </q-btn>
        <q-btn
          color="primary"
          dense
          :disable="!workspace.canEdit"
          :icon="icons.confirm"
          round
          size="sm"
          unelevated
          @click="promptCommit()"
        >
          <q-tooltip>Commit Changes</q-tooltip>
        </q-btn>
      </template>
    </div>
  </full-page>
</template>

<style lang="scss" module>
.root {
  overflow-x: hidden;
}

.shortcut {
  font-size: 11px;
  opacity: 0.6;
}

// Redo is the undo arrow mirrored, which reads as its opposite without needing a second icon.
.redoIcon {
  transform: scaleX(-1);
}

.nameEditable:hover {
  opacity: 0.6;
}

.verticalResizeHandle {
  position: absolute;
  left: 0px;
  bottom: -4.5px;
  z-index: 1;
}

.horizontalResizeHandle {
  position: absolute;
  right: -0.5px;
  top: 0px;
  z-index: 1;
}

.addWidgetRow {
  cursor: pointer;
  padding: 4px 0;
}

.bottomPadding {
  height: 250px;
}

// Floats over the bottom of the workspace. Sticky would only pin it while the page scrolls, and
// a short workspace does not, which would drop the bar below the fold exactly when there is least
// reason to hunt for it.
.actionBar {
  position: fixed;
  z-index: 3;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  width: fit-content;
  padding: 4px 8px;
  border-radius: 999px;
  backdrop-filter: blur(6px);
}

:global(.dark) .actionBar {
  background-color: rgba(0, 0, 0, 0.65);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
}

:global(.light) .actionBar {
  background-color: rgba(255, 255, 255, 0.85);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

// Redo is the undo arrow mirrored, which reads as its opposite without needing a second icon.
.redoButton :global(.q-icon) {
  transform: scaleX(-1);
}

.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
}

@mixin gap {
  position: absolute;
}

.gapVerticalTop {
  @include gap;
  top: -10px;
  left: 0;
}

.gapVerticalBottom {
  @include gap;
  bottom: -10px;
  left: 0;
}

.gapHorizontalLeft {
  @include gap;
  left: -5px;
}

.gapHorizontalMiddle {
  @include gap;
  left: -6px;
}

.gapHorizontalRight {
  @include gap;
  right: -5px;
}

.draggedWidgetIcon {
  position: fixed;
  z-index: 5000;
  pointer-events: none;
}

.draggedWidget {
  opacity: 0.5;
}
</style>
