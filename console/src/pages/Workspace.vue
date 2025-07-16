<script lang="ts" setup>
import { useEventListener, useMouse, useResizeObserver } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { QPopupEdit } from 'quasar'
import { onMounted, reactive, watchEffect, watch } from 'vue'

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
import { provideWorkspace, resolveWidgetWidths, Widget, WorkspaceData } from '@/workspace'

const { id } = $defineProps<{
  id: string
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()

const workspace = provideWorkspace(id)
await workspace.load()

const layout = $ref<HTMLDivElement | null>(null)
let originalData = $ref<WorkspaceData | null>(null)
let isViewingOriginal = $computed(() => originalData != null)

if (workspace.data == null || workspace.name == null) {
  throw new NotFoundError('workspace', id)
}

async function startViewingOriginal() {
  await workspace.refresh()
  originalData = deepClone(workspace.originalData) as WorkspaceData
  key++
}

function stopViewingOriginal() {
  originalData = null
  key++
}

const data = $computed(() => {
  if (isViewingOriginal) {
    return originalData
  } else {
    return workspace.data
  }
})

let key = $ref(0)

let name = $ref<string>(workspace.name)
watch(
  () => name,
  async () => {
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

function promptLeave() {
  dialogs
    .confirm({
      title: 'Leave Workspace',
      message:
        `Are you sure you want to leave workspace "${workspace.name}"?\n\n` +
        'You will no longer be a member, and if this workspace does not allow general access for ' +
        "your account's role, you will not be able to rejoin on your own.",
      ok: {
        label: 'Leave',
        color: 'negative',
      },
    })
    .onOk(async () => {
      await workspace.leave()
      await navigation.go('/')
    })
}

function promptDelete() {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message:
        `Are you sure you want to delete workspace "${workspace.name}"?\n\n` +
        'This action cannot be undone, and any users with access to this workspace will never ' +
        'be able to use it again.',
    })
    .onOk(async () => {
      await workspace.delete()
      await navigation.go('/')
    })
}

function promptCommit() {
  dialogs
    .confirm({
      title: 'Commit Changes',
      message:
        `Commit changes to workspace "${workspace.name}"? ` +
        'This will update the current shared version of this workspace, allowing users with ' +
        'access to see this version.',
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

function promptDiscard() {
  dialogs
    .confirm({
      title: 'Discard Changes',
      message:
        `This action will discard all changes to workspace "${workspace.name}" and revert your ` +
        'working copy to the latest shared version. This will not modify the workspace for other ' +
        'users.',
      ok: {
        label: 'Discard',
        color: 'warning',
      },
    })
    .onOk(async () => {
      await workspace.discard()
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

  const width = `${Math.round((widget.width / 100) * layoutWidth).toFixed(1)}px`

  return {
    maxWidth: width,
    minWidth: width,
  }
}

onMounted(() => {
  resolveAllWidgetWidths()
})
</script>

<template>
  <full-page :class="$style.root">
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
      <div>
        <common-text
          class="q-ml-md q-mr-xs q-py-sm"
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
      <q-separator class="q-my-md" spaced="md" vertical />
      <q-chip
        v-if="workspace.membership == null"
        class="no-shadow"
        clickable
        :icon="icons.join"
        size="sm"
      >
        Join
        <q-menu class="no-shadow" :offset="[0, 8]">
          <q-card bordered flat>
            <q-list dense>
              <q-item v-close-popup clickable @click="workspace.join('viewer')">
                <q-item-section avatar>
                  <q-icon :name="icons.viewer" />
                </q-item-section>
                <q-item-section>As Viewer</q-item-section>
              </q-item>
              <q-item v-close-popup clickable @click="workspace.join('editor')">
                <q-item-section avatar>
                  <q-icon :name="icons.editor" />
                </q-item-section>
                <q-item-section>As Editor</q-item-section>
              </q-item>
              <q-item v-close-popup clickable @click="workspace.join('manager')">
                <q-item-section avatar>
                  <q-icon :name="icons.manager" />
                </q-item-section>
                <q-item-section>As Manager</q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </q-menu>
      </q-chip>
      <q-chip
        v-else
        class="no-shadow q-px-sm"
        color="primary"
        dense
        flat
        :icon="icons[workspace.membership.role]"
        size="sm"
        text-color="white"
      >
        {{ upperFirst(workspace.membership.role) }}
        <q-tooltip class="bg-primary text-white" :delay="500">
          You are {{ workspace.membership.role === 'editor' ? 'an' : 'a' }}
          {{ workspace.membership.role }} of this workspace.
        </q-tooltip>
      </q-chip>
      <q-btn
        v-if="workspace.data != null"
        class="faded-hover q-ml-xs"
        flat
        :icon="icons.more"
        round
        size="8px"
      >
        <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
          <q-list bordered dense>
            <q-item
              v-close-popup
              clickable
              dense
              @click="dialogs.workspaceSettings(id).onOk(() => workspace.refresh())"
            >
              <q-item-section avatar>
                <q-icon :name="icons.settings" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Settings</q-item-label>
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
            <q-item v-if="workspace.canManage" v-close-popup clickable dense @click="promptDelete">
              <q-item-section avatar>
                <q-icon :name="icons.delete" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Delete</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-close-popup clickable @click="promptLeave">
              <q-item-section avatar>
                <q-icon :name="icons.leave" />
              </q-item-section>
              <q-item-section>Leave</q-item-section>
            </q-item>
            <q-separator />
            <q-item v-close-popup clickable dense>
              <q-item-section avatar>
                <q-icon :name="icons.add" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Add Widget</q-item-label>
              </q-item-section>
              <workspace-add-widget-menu :row="-1" />
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
      <q-space />
      <div class="q-mr-md">
        <q-btn
          v-if="workspace.edited && isViewingOriginal"
          clickable
          color="primary"
          dense
          :icon="icons.close"
          label="Stop Viewing Original"
          size="sm"
          @click="stopViewingOriginal"
        />
        <q-chip
          v-else-if="workspace.edited"
          clickable
          color="warning"
          dense
          label="Working Copy"
          size="12px"
          square
        >
          <q-menu class="no-shadow" :offset="[0, 10]">
            <q-card bordered style="min-width: 140px">
              <q-list dense>
                <q-item clickable :disable="!workspace.canEdit" @click="promptCommit">
                  <q-item-section>
                    <q-item-label>Commit Changes</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item clickable @click="promptDiscard">
                  <q-item-section>
                    <q-item-label>Discard Changes</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item clickable @click="startViewingOriginal">
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
    <div :key="key" class="q-pa-xs" :style="isViewingOriginal && { border: `1px solid yellow` }">
      <div v-if="data == null" ref="layout" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists.</div>
      </div>
      <div v-else ref="layout">
        <div
          v-for="(row, i) in data.layout"
          :key="row.id"
          class="full-width no-wrap q-gutter-xs q-py-xs relative-position row"
          :style="{ height: row.collapsed ? undefined : `${row.height}px` }"
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
            hidden
            :min="150"
          />
          <div
            v-for="(widget, j) in row.widgets"
            :key="widget.id"
            :class="[j < row.widgets.length - 1 ? 'col-shrink' : 'col-grow', 'relative-position']"
            :style="j === row.widgets.length - 1 ? undefined : getWidgetWidthStyle(widget)"
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
              hidden
              :min="100"
              :model-value="(widget.width / 100) * layoutWidth"
              @update:model-value="
                (pixels) => {
                  if (layoutWidth == null) {
                    return
                  }

                  widget.width = (pixels / layoutWidth) * 100
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
    <div v-if="!isViewingOriginal" class="faded-hover items-center justify-center q-mt-sm row">
      <q-btn v-if="data != null" color="primary" :icon="icons.add" round size="8px">
        <q-tooltip class="bg-primary">Add Widget</q-tooltip>
        <workspace-add-widget-menu :offset="[0, 8]" :row="data.layout.length" />
      </q-btn>
    </div>
    <div :class="$style.bottomPadding" />
  </full-page>
</template>

<style lang="scss" module>
.root {
  overflow-x: hidden;
}

.nameEditable:hover {
  color: grey !important;
}

.verticalResizeHandle {
  position: absolute;
  left: -2px;
  bottom: 4px;
  z-index: 1;
}

.horizontalResizeHandle {
  position: absolute;
  right: -2.5px;
  top: 0px;
  z-index: 1;
}

.bottomPadding {
  height: 250px;
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
  top: -2px;
  left: 0;
}

.gapVerticalBottom {
  @include gap;
  bottom: -2px;
  left: 0;
}

.gapHorizontalLeft {
  @include gap;
  left: -5.5px;
}

.gapHorizontalMiddle {
  @include gap;
  left: -8px;
}

.gapHorizontalRight {
  @include gap;
  right: -5.5px;
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
