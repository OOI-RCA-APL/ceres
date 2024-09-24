<script lang="ts" setup>
import { useEventListener, useMouse } from '@vueuse/core'
import { QPopupEdit } from 'quasar'
import { computed, reactive, watchEffect } from 'vue'

import AddWidgetMenu from '@/components/AddWidgetMenu.vue'
import AlertView from '@/components/AlertView.vue'
import CommonText from '@/components/CommonText.vue'
import FullPage from '@/components/FullPage.vue'
import LogEntryView from '@/components/LogEntryView.vue'
import MessageView from '@/components/MessageView.vue'
import ProcedureView from '@/components/ProcedureView.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import UiView from '@/components/UiView.vue'
import WorkspaceGap from '@/components/WorkspaceGap.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { Drag, provideWorkspaceContext, useWorkspaces } from '@/workspace'

const { name } = defineProps<{
  name: string
}>()

const workspaces = useWorkspaces()
const dialogs = useDialogs()
const context = provideWorkspaceContext({
  name: computed(() => name),
})

let renamePopup = $ref<QPopupEdit | null>(null)

function startDrag(value: Drag) {
  context.drag = value
}

function clearDrag() {
  context.drag = null
}

useEventListener(window, 'mouseup', () => {
  clearDrag()
})

watchEffect(() => {
  if (context.drag != null) {
    document.body.style.cursor = 'grabbing'
  } else {
    document.body.style.cursor = 'unset'
  }
})

const mouse = reactive(useMouse({ type: 'client' }))
const draggedWidgetStyle = $computed(() => ({
  left: `${mouse.x}px`,
  top: `${mouse.y}px`,
  transform: 'translate(-50%, -50%)',
}))

let nameValue = $computed({
  get: () => context.name,
  set: (value: string) => {
    if (value == context.name) {
      return
    }

    const workspace = context.rename(value)
    if (workspace != null) {
      workspaces.open(workspace.name)
    }
  },
})

function copy() {
  const copied = context.copy()
  if (copied != null) {
    workspaces.open(copied.name)
  }
}

function promptDelete() {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message: `Are you sure you want to delete workspace "${context.name}"?`,
    })
    .onOk(() => {
      context.delete()
    })
}
</script>

<template>
  <full-page :class="$style.root">
    <div
      v-if="context.drag != null"
      key="dragged-widget"
      :class="$style.draggedWidget"
      :style="draggedWidgetStyle"
    >
      <q-card bordered class="q-px-xs" flat>
        <common-text variant="th">
          {{ context.drag.widget.name }}
        </common-text>
      </q-card>
    </div>
    <template #header-append>
      <div>
        <common-text class="q-ml-md q-py-sm" variant="title2">
          {{ context.name }}
        </common-text>
        <q-popup-edit
          v-if="context.workspace != null"
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
        v-if="context.workspace != null"
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
            <q-item v-close-popup clickable dense @click="copy">
              <q-item-section avatar>
                <q-icon :name="icons.copy" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Copy</q-item-label>
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
            <q-item clickable dense>
              <q-item-section avatar>
                <q-icon :name="icons.add" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Add Widget</q-item-label>
              </q-item-section>
              <add-widget-menu :row="-1" />
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
    </template>
    <div class="q-pa-xs">
      <div v-if="context.workspace == null" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists. Create it?</div>
        <q-btn class="q-mt-md" color="primary" dense label="Create" @click="context.create" />
      </div>
      <div v-else>
        <div
          v-for="(row, i) in context.workspace.layout"
          :key="i"
          class="full-width no-wrap q-gutter-xs q-py-xs relative-position row"
          :style="{ height: row.collapsed ? undefined : `${row.height}px` }"
        >
          <workspace-gap
            v-if="context.drag != null"
            :class="$style.gapVerticalTop"
            direction="vertical"
            :row="i"
          />
          <workspace-gap
            v-if="context.drag != null && i === context.workspace.layout.length - 1"
            v-show="context.drag != null"
            :class="$style.gapVerticalBottom"
            direction="vertical"
            :row="i + 1"
          />
          <resize-handle
            v-if="context.drag == null && !row.collapsed"
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
            :style="j < row.widgets.length - 1 ? { width: `${widget.width}px` } : undefined"
          >
            <template v-if="context.drag != null">
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
                v-if="context.drag != null && j === row.widgets.length - 1"
                :class="$style.gapHorizontalRight"
                :column="j + 1"
                direction="horizontal"
                :row="i"
              />
            </template>
            <resize-handle
              v-if="context.drag == null && j < row.widgets.length - 1"
              v-model="widget.width"
              :class="$style.horizontalResizeHandle"
              direction="horizontal"
              hidden
              :min="100"
            />
            <q-card bordered class="col column full-height" flat>
              <div
                class="q-px-sm q-py-xs"
                :style="{ cursor: context.drag != null ? 'grabbing' : 'grab' }"
                @mousedown.prevent="startDrag({ widget, row: i, column: j })"
                @mousemove.prevent
                @touchmove.prevent
                @touchstart.prevent="startDrag({ widget, row: i, column: j })"
              >
                <div class="items-center row">
                  <div>
                    <common-text
                      class="text-capitalize"
                      style="cursor: text"
                      variant="th"
                      @mousedown.stop
                      @touchstart.stop
                    >
                      {{ widget.name }}
                      <q-popup-edit
                        v-slot="scope"
                        v-model="widget.name"
                        auto-save
                        :class="$style.popupEdit"
                        self="top left"
                        :validate="(value: string) => value.trim() !== ''"
                      >
                        <q-card bordered class="q-pa-sm" flat style="max-width: 200px">
                          <q-input
                            v-model.trim="scope.value"
                            autofocus
                            dense
                            filled
                            label="Widget Name"
                            @keyup.enter="scope.set()"
                          />
                        </q-card>
                      </q-popup-edit>
                    </common-text>
                  </div>
                  <div>
                    <q-btn
                      class="faded-hover q-ml-xs"
                      flat
                      :icon="icons.more"
                      round
                      size="6px"
                      @mousedown.stop
                      @touchstart.stop
                    >
                      <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
                        <q-list bordered>
                          <q-item
                            v-close-popup
                            clickable
                            dense
                            @click="context.copyWidget(widget.id, i, j + 1)"
                          >
                            <q-item-section avatar>
                              <q-icon :name="icons.duplicate" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>Duplicate</q-item-label>
                            </q-item-section>
                          </q-item>
                          <q-separator />
                          <q-item clickable dense>
                            <q-item-section avatar>
                              <q-icon :name="icons.add" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>Add Widget Before</q-item-label>
                            </q-item-section>
                            <add-widget-menu :column="j - 1" :row="i" />
                          </q-item>
                          <q-item clickable dense>
                            <q-item-section avatar>
                              <q-icon :name="icons.add" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>Add Widget After</q-item-label>
                            </q-item-section>
                            <add-widget-menu :column="j + 1" :row="i" />
                          </q-item>
                          <q-separator />
                          <q-item
                            v-close-popup
                            clickable
                            dense
                            @click="context.deleteWidget(widget.id)"
                          >
                            <q-item-section avatar>
                              <q-icon :name="icons.delete" />
                            </q-item-section>
                            <q-item-section>
                              <q-item-label>Delete</q-item-label>
                            </q-item-section>
                          </q-item>
                        </q-list>
                      </q-menu>
                    </q-btn>
                  </div>
                  <q-space />
                  <q-btn
                    flat
                    round
                    size="6px"
                    @click.prevent="row.collapsed = !row.collapsed"
                    @mousedown.stop
                    @touchstart.stop
                  >
                    <q-icon :name="row.collapsed ? icons.menuDown : icons.menuUp" size="12px" />
                  </q-btn>
                </div>
              </div>
              <template v-if="!row.collapsed">
                <q-separator />
                <div class="col-grow overflow-auto q-pa-sm" style="height: 0">
                  <template v-if="widget.type === 'messages'">
                    <message-view class="full-height" :widget="widget" />
                  </template>
                  <template v-else-if="widget.type === 'alerts'">
                    <alert-view class="full-height" :persist="`widget/${widget.id}`" />
                  </template>
                  <template v-else-if="widget.type === 'logs'">
                    <log-entry-view class="full-height" :persist="`widget/${widget.id}`" />
                  </template>
                  <template v-else-if="widget.type === 'procedures'">
                    <procedure-view :widget="widget" />
                  </template>
                  <template v-else-if="widget.type === 'ui'">
                    <ui-view :widget="widget" />
                  </template>
                </div>
              </template>
            </q-card>
          </div>
        </div>
      </div>
    </div>
    <div class="faded-hover items-center justify-center q-mt-sm row">
      <q-btn v-if="context.workspace != null" color="primary" :icon="icons.add" round size="8px">
        <q-tooltip class="bg-primary">Add Widget</q-tooltip>
        <add-widget-menu :offset="[0, 8]" :row="context.workspace.layout.length" />
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
  left: 0;
  bottom: 4px;
  z-index: 100;
}

.horizontalResizeHandle {
  position: absolute;
  right: -3px;
  top: 0px;
  z-index: 100;
}

.bottomPadding {
  height: 250px;
}

.popupEdit {
  // max-width: 200px;
  // min-width: unset !important;
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

.draggedWidget {
  position: fixed;
  z-index: 5000;
  pointer-events: none;
}
</style>
