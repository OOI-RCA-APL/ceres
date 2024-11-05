<script lang="ts" setup>
import { useEventListener, useMouse, useResizeObserver } from '@vueuse/core'
import { QPopupEdit } from 'quasar'
import { computed, onMounted, reactive, watchEffect } from 'vue'

import CommonText from '@/components/CommonText.vue'
import FullPage from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceGap from '@/components/WorkspaceGap.vue'
import WorkspaceWidget from '@/components/WorkspaceWidget.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { provideWorkspace, resolveWidgetWidths, useWorkspaces, Widget } from '@/workspace'

const { name } = $defineProps<{
  name: string
}>()

const workspaces = useWorkspaces()
const dialogs = useDialogs()
const layout = $ref<HTMLDivElement | null>(null)
const workspace = provideWorkspace({
  name: computed(() => name),
})

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

let nameValue = $computed({
  get: () => workspace.name,
  set: (value: string) => {
    if (value == workspace.name) {
      return
    }

    const renamed = workspace.rename(value)
    if (renamed != null) {
      workspaces.open(renamed.name)
    }
  },
})

function duplicate() {
  const copied = workspace.duplicate()
  if (copied != null) {
    workspaces.open(copied.name)
  }
}

function promptDelete() {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message: `Are you sure you want to delete workspace "${workspace.name}"?`,
    })
    .onOk(() => {
      workspace.delete()
    })
}

function resolveAllWidgetWidths() {
  if (workspace.data == null) {
    return
  }

  for (const row of workspace.data.layout) {
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
        <common-text class="q-ml-md q-py-sm" variant="title2">
          {{ workspace.name }}
        </common-text>
        <q-popup-edit
          v-if="workspace.data != null"
          ref="renamePopup"
          v-slot="scope"
          v-model="nameValue"
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
      <q-btn
        v-if="workspace.data != null"
        class="faded-hover q-ml-xs"
        flat
        :icon="icons.more"
        round
        size="8px"
      >
        <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
          <q-list bordered>
            <q-item v-close-popup clickable dense @click="renamePopup?.show()">
              <q-item-section avatar>
                <q-icon :name="icons.rename" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Rename</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-close-popup clickable dense @click="duplicate">
              <q-item-section avatar>
                <q-icon :name="icons.duplicate" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Duplicate</q-item-label>
              </q-item-section>
            </q-item>
            <q-item
              clickable
              dense
              :disable="workspace.data == null"
              @click="workspaces.exportFile(workspace.name)"
            >
              <q-item-section avatar>
                <q-icon :name="icons.export" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Export</q-item-label>
              </q-item-section>
            </q-item>
            <q-item clickable dense @click="promptDelete">
              <q-item-section avatar>
                <q-icon :name="icons.delete" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Delete</q-item-label>
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
              <workspace-add-widget-menu :row="-1" />
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </template>
    <div class="q-pa-xs">
      <div v-if="workspace.data == null" ref="layout" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists. Create it?</div>
        <q-btn class="q-mt-md" color="primary" dense label="Create" @click="workspace.create" />
      </div>
      <div v-else ref="layout">
        <div
          v-for="(row, i) in workspace.data.layout"
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
            v-if="workspace.drag != null && i === workspace.data.layout.length - 1"
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
    <div class="faded-hover items-center justify-center q-mt-sm row">
      <q-btn v-if="workspace.data != null" color="primary" :icon="icons.add" round size="8px">
        <q-tooltip class="bg-primary">Add Widget</q-tooltip>
        <WorkspaceAddWidgetMenu :offset="[0, 8]" :row="workspace.data.layout.length" />
      </q-btn>
    </div>
    <div :class="$style.bottomPadding" />
  </full-page>
</template>

<style lang="scss" module>
.root {
  overflow-x: hidden;
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
