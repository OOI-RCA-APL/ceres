<script lang="ts" setup>
import { useElementBounding, useEventListener, useMouse, useResizeObserver } from '@vueuse/core'
import { colors } from 'quasar'
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

function isTyping(target: EventTarget | null) {
  const element = target as HTMLElement | null

  return (
    element?.isContentEditable === true || ['INPUT', 'TEXTAREA'].includes(element?.tagName ?? '')
  )
}

// Copy, cut and paste carry widgets through the system clipboard, so a block of a workspace can be
// taken to another workspace or another window. Text the user has actually highlighted is left to
// the browser, since copying a value out of a widget is the more likely thing to want.
useEventListener(window, 'copy', (event: ClipboardEvent) => {
  const text = onCopy(event)
  if (text != null) {
    notify.success(`${workspace.selection.length} widget(s) copied.`)
  }
})

useEventListener(window, 'cut', (event: ClipboardEvent) => {
  const count = workspace.selection.length
  const text = onCopy(event)
  if (text != null) {
    workspace.deleteWidgets([...workspace.selection])
    notify.success(`${count} widget(s) cut.`)
  }
})

useEventListener(window, 'paste', (event: ClipboardEvent) => {
  if (isTyping(event.target)) {
    return
  }

  const pasted = workspace.pasteWidgets(event.clipboardData?.getData('text/plain') ?? '')
  if (pasted > 0) {
    event.preventDefault()
  }
})

function onCopy(event: ClipboardEvent): string | null {
  if (isTyping(event.target) || (window.getSelection()?.toString() ?? '') !== '') {
    return null
  }

  const text = workspace.copySelection()
  if (text == null) {
    return null
  }

  event.preventDefault()
  event.clipboardData?.setData('text/plain', text)

  return text
}

// Shortcuts that act on the workspace, skipped while the user is typing so a text field keeps its
// own behavior.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (isTyping(event.target)) {
    return
  }

  // Undo and redo on the usual shortcuts. Redo accepts both spellings, since editors are split
  // between them.
  if ((event.metaKey || event.ctrlKey) && !event.altKey) {
    const key = event.key.toLowerCase()
    if (key === 'z' && !event.shiftKey) {
      event.preventDefault()
      workspace.undo()
    } else if ((key === 'z' && event.shiftKey) || key === 'y') {
      event.preventDefault()
      workspace.redo()
    }

    return
  }

  // Delete takes out whatever is picked out, in one step that a single undo puts back. Both
  // spellings, since the key a Mac keyboard labels delete reports itself as backspace.
  if (
    (event.key === 'Delete' || event.key === 'Backspace') &&
    workspace.drag == null &&
    workspace.selection.length > 0
  ) {
    event.preventDefault()
    workspace.deleteWidgets([...workspace.selection])
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

function isHeld(widget: Widget) {
  return drop.active && workspace.drag?.widgets.some((held) => held.id === widget.id) === true
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

// Exposed through the `header-prepend` slot, which is the tab strip a workspace is shown on and
// the only place these are reached from. This page draws the widgets and nothing around them.
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
  <full-page :class="$style.root" dense :sticky-top="stickyTop">
    <div
      v-if="drop.active && workspace.drag != null"
      key="dragged-widget-icon"
      :class="$style.draggedWidgetIcon"
      :style="draggedWidgetIconStyle"
    >
      <q-card bordered class="items-center q-px-xs row" flat>
        <common-text variant="th">
          {{ workspace.drag.widget.name }}
        </common-text>
        <q-badge
          v-if="workspace.drag.widgets.length > 1"
          class="q-ml-xs"
          color="primary"
          :label="`+${workspace.drag.widgets.length - 1}`"
        />
      </q-card>
    </div>
    <template #header-append>
      <slot :actions="headerActions" name="header-prepend" :state="headerState" />
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
            <workspace-widget-placeholder v-if="isHeld(widget)" :widget="widget" />
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
