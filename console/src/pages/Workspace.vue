<script lang="ts" setup>
import { useElementBounding, useEventListener, useMouse, useResizeObserver } from '@vueuse/core'
import { QPopupEdit, colors } from 'quasar'
import { computed, onMounted, reactive, watchEffect, watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import FullPage, { appHeaderHeight, densePageHeaderHeight } from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceWidget from '@/components/WorkspaceWidget.vue'
import WorkspaceWidgetPlaceholder from '@/components/WorkspaceWidgetPlaceholder.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError } from '@/errors'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { deepClone } from '@/utilities'
import { useWidgetDrop } from '@/widget-drop'
import {
  provideWorkspace,
  resolveWidgetWidths,
  widgetWidthSubdivisions,
  Widget,
  WidgetRow,
  Workspace,
  WorkspaceData,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
  getWidgetInfo,
} from '@/workspace'

const { id, stickyTop } = defineProps<{
  id: string

  /** Where the workspace header pins, raised when it sits under another page's header. */
  stickyTop?: number
}>()

const emit = defineEmits<{
  /** A copy, for the page hosting this one to place beside the workspace it was copied from. */
  duplicated: [afterId: string, id: string]
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()

const workspace = provideWorkspace(computed(() => id))
await workspace.load()

// One viewport below where the tab strip pins. That is the least this page can be and still let
// the strip reach its pinned position, and it does not depend on how tall any one workspace is,
// so every workspace on a strip can be scrolled the same distance.
const bottomRoom = $computed(
  () => `calc(100vh - ${(stickyTop ?? appHeaderHeight) + densePageHeaderHeight + 1}px)`
)

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

const drop = useWidgetDrop(workspace, () => layout)

// While a widget is in hand the layout on screen is the one letting go would produce, which puts
// the drop target where the widget itself will be rather than beside a mark standing in for it.
const rows = $computed<WidgetRow[]>(() => {
  if (data == null) {
    return []
  }
  if (drop.plan == null) {
    return data.layout
  }

  const widgets = new Map(
    data.layout.flatMap((row) => row.widgets).map((widget) => [widget.id, widget])
  )
  const current = new Map(data.layout.map((row) => [row.id, row]))

  return drop.plan.rows.map((row) => {
    const contents = row.widgets.map((id) => widgets.get(id)).filter((widget) => widget != null)

    // Rows the move leaves alone keep the identity they already had, so the widgets inside them
    // are not handed a fresh container on every pointer move.
    const unchanged = current.get(row.id) ?? null
    if (
      unchanged != null &&
      unchanged.height === row.height &&
      unchanged.collapsed === row.collapsed &&
      unchanged.widgets.length === contents.length &&
      unchanged.widgets.every((widget, index) => widget === contents[index])
    ) {
      return unchanged
    }

    return { id: row.id, height: row.height, collapsed: row.collapsed, widgets: contents }
  })
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

// The action bar floats over the window rather than sitting in the page, so its center is taken
// from the widgets it acts on. Half the window is somewhere left of them whenever the drawer is
// open, which reads as misaligned against everything else on the page.
const layoutBounds = useElementBounding($$(layout))
const actionBarStyle = $computed(() => ({
  left: `${layoutBounds.x.value + layoutBounds.width.value / 2}px`,
}))

watchEffect(() => {
  if (drop.active) {
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
  dialogs.duplicateWorkspace(id, data as WorkspaceData).onOk((created: Workspace) => {
    emit('duplicated', id, created.id)
  })
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

  const units = drop.plan?.widths[widget.id] ?? widget.width
  const width = `${Math.round((units / widgetWidthSubdivisions) * layoutWidth).toFixed(1)}px`

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
  <full-page :class="$style.root" :dense="$slots['header-prepend'] != null" :sticky-top="stickyTop">
    <div
      v-if="drop.active && workspace.drag != null"
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
      :class="$style.layout"
      :style="isViewingOriginal && { border: `1px dashed ${colors.getPaletteColor('warning')}` }"
    >
      <div v-if="workspace.loading" ref="layout" class="q-py-lg" />
      <div v-else-if="data == null" ref="layout" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists.</div>
      </div>
      <div v-else ref="layout">
        <div
          v-for="(row, i) in rows"
          :key="row.id"
          class="full-width no-wrap q-my-sm relative-position row"
          data-row
          :style="{
            height: row.collapsed ? undefined : `${row.height}px`,
          }"
        >
          <resize-handle
            v-if="!drop.active && !row.collapsed"
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
            data-widget
            :style="j < row.widgets.length - 1 ? getWidgetWidthStyle(widget) : undefined"
          >
            <resize-handle
              v-if="layoutWidth && !drop.active && j < row.widgets.length - 1"
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
            <workspace-widget-placeholder
              v-if="drop.active && workspace.drag?.widget.id === widget.id"
              :widget="widget"
            />
            <workspace-widget v-else :column="j" :container="row" :row="i" :widget="widget" />
          </div>
        </div>
      </div>
    </div>
    <div
      v-if="!isViewingOriginal && data != null"
      class="row"
      :class="[$style.addWidgetRow, 'items-center', 'justify-center', 'q-mt-sm']"
    >
      <q-btn aria-label="Add Widget" color="primary" :icon="icons.add" round size="8px" unelevated>
        <q-tooltip class="bg-primary">Add Widget</q-tooltip>
        <workspace-add-widget-menu
          anchor="bottom middle"
          :offset="[0, 8]"
          :row="data.layout.length"
          self="top middle"
        />
      </q-btn>
    </div>
    <!-- Room below the widgets for the tab strip to be scrolled up to where it pins, whatever this
    workspace happens to hold. A workspace shorter than this cannot be scrolled far enough to stick
    the strip at all, and switching to one from a taller workspace would drop the strip back down
    the page as the document shrank under it. -->
    <div :class="$style.bottomPadding" :style="{ minHeight: bottomRoom }" />
    <!-- A working copy is normally an ongoing personal state rather than a staging area, so the
    bar reads as neutral status. It appears only while one exists, and the same actions stay in the
    tab's menu, since this is a shortcut rather than the only route to them. -->
    <div
      v-if="workspace.edited"
      :class="[$style.actionBar, 'items-center', 'row']"
      :style="actionBarStyle"
    >
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
          <q-tooltip class="bg-primary text-white">Revert to Original Version</q-tooltip>
        </q-btn>
        <q-btn dense flat :icon="icons.close" round size="sm" @click="stopViewingOriginal()">
          <q-tooltip class="bg-primary text-white">Stop Viewing Original</q-tooltip>
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
          <q-tooltip class="bg-primary text-white">View Original</q-tooltip>
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
          <q-tooltip class="bg-primary text-white">Commit Changes</q-tooltip>
        </q-btn>
      </template>
    </div>
  </full-page>
</template>

<style lang="scss" module>
// Clipped here rather than on the page, because hiding an axis makes an element its own scrolling
// box, and a header inside one pins to that box instead of to the window.
.layout {
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
  padding: 4px 0;
}

// A floor rather than a fixed height, since the minimum is set inline from where this page's
// header pins.
.bottomPadding {
  height: 250px;
}

// Rests on the bottom edge of the window, rounded only where it meets the page. Sticky would pin
// it only while the page scrolls, and a short workspace does not, which would drop the bar below
// the fold exactly when there is least reason to hunt for it. Its horizontal position is set
// inline, from the widgets it acts on.
//
// Spaced with `gap` rather than a Quasar gutter, whose negative margins offset the box against
// its own contents and leave the buttons sitting low and right of center.
.actionBar {
  position: fixed;
  z-index: 4;
  bottom: 0;
  transform: translateX(-50%);
  width: fit-content;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 8px 8px 0 0;
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

.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
}

.draggedWidgetIcon {
  position: fixed;
  z-index: 5000;
  pointer-events: none;
}
</style>
