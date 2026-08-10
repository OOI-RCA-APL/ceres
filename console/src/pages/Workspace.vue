<script lang="ts" setup>
import { useElementBounding, useEventListener, useMouse } from '@vueuse/core'
import { colors } from 'quasar'
import { computed, reactive, watchEffect, watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import FullPage, { appHeaderHeight, densePageHeaderHeight } from '@/components/FullPage.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceLayout from '@/components/WorkspaceLayout.vue'
import WorkspaceWidgetGroupDialog from '@/components/WorkspaceWidgetGroupDialog.vue'
import { useDialogs } from '@/dialogs'
import { NotFoundError } from '@/errors'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { deepClone } from '@/utilities'
import { provideWidgetDrop } from '@/widget-drop'
import {
  provideWorkspace,
  rootLayoutId,
  Workspace,
  WorkspaceData,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
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
// the strip reach its pinned position, and it does not depend on how tall any one workspace is
// so every workspace on a strip can be scrolled the same distance.
const bottomRoom = $computed(
  () => `calc(100vh - ${(stickyTop ?? appHeaderHeight) + densePageHeaderHeight + 1}px)`
)

const layoutView = $ref<InstanceType<typeof WorkspaceLayout> | null>(null)

/** The box the widgets are laid out in, which a drag is measured against. */
const layoutElement = $computed(() => layoutView?.element ?? null)

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
// Started here and reached by every layout drawn under this page since a carousel slide is
// arranged the same way the workspace is and a drag crosses freely between them.
const drop = provideWidgetDrop(workspace)

function isTyping(target: EventTarget | null) {
  const element = target as HTMLElement | null

  return (
    element?.isContentEditable === true || ['INPUT', 'TEXTAREA'].includes(element?.tagName ?? '')
  )
}

// Copy, cut and paste carry widgets through the system clipboard so a block of a workspace can be
// taken to another workspace or another window. Text the user has actually highlighted is left to
// the browser since copying a value out of a widget is the more likely thing to want.
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

// The widgets the group dialog was opened for, or null while it is closed. Named here as well as
// in each widget's menu so the keyboard can reach grouping without a widget menu open.
let groupDialogIds = $ref<string[] | null>(null)

// Shortcuts that act on the workspace, skipped while the user is typing so a text field keeps its
// own behavior.
useEventListener(window, 'keydown', (event: KeyboardEvent) => {
  if (isTyping(event.target)) {
    return
  }

  // Undo and redo on the usual shortcuts. Redo accepts both spellings since editors are split
  // between them.
  if ((event.metaKey || event.ctrlKey) && !event.altKey) {
    const key = event.key.toLowerCase()
    if (key === 'z' && !event.shiftKey) {
      event.preventDefault()
      workspace.undo()
    } else if ((key === 'z' && event.shiftKey) || key === 'y') {
      event.preventDefault()
      workspace.redo()
    } else if (key === 'g' && workspace.selection.length > 0) {
      // Group and ungroup on the shortcuts design tools taught, acting on what is picked out.
      // Ungrouping quietly does nothing when the one picked-out widget holds no pages.
      event.preventDefault()
      if (event.shiftKey) {
        if (workspace.selection.length === 1 && workspace.selection[0] != null) {
          workspace.ungroupWidget(workspace.selection[0])
        }
      } else {
        groupDialogIds = [...workspace.selection]
      }
    }

    return
  }

  // Delete takes out whatever is picked out, in one step that a single undo puts back. Both
  // spellings since the key a Mac keyboard labels delete reports itself as backspace.
  if (
    (event.key === 'Delete' || event.key === 'Backspace') &&
    workspace.drag == null &&
    workspace.selection.length > 0
  ) {
    event.preventDefault()
    workspace.deleteWidgets([...workspace.selection])
  }
})

// The action bar floats over the window rather than sitting in the page so its center is taken
// from the widgets it acts on. Half the window is somewhere left of them whenever the drawer is
// open, which reads as misaligned against everything else on the page.
const layoutBounds = useElementBounding($$(layoutElement))
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

      // A component-placed workspace is hosted by that component's page so deleting it
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
      <div v-if="workspace.loading" class="q-py-lg" />
      <div v-else-if="data == null" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists.</div>
      </div>
      <workspace-layout v-else ref="layoutView" :layout="data.layout" :layout-id="rootLayoutId" />
    </div>
    <!-- Mounted only while showing so its remembered choices are read fresh each time. -->
    <workspace-widget-group-dialog
      v-if="groupDialogIds != null"
      :widget-ids="groupDialogIds"
      @close="groupDialogIds = null"
    />
    <!-- Held back while the layout is empty since a layout with nothing on it offers this same
    button in the middle of itself and two of it on screen at once is one too many. -->
    <div
      v-if="!isViewingOriginal && data != null && data.layout.length > 0"
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
    <!-- Room below the widgets so the tab strip can always be scrolled to where it pins. A
    shorter workspace could not pin the strip, and switching to it from a taller one would drop
    the strip back down the page as the document shrank. -->
    <div :class="$style.bottomPadding" :style="{ minHeight: bottomRoom }" />
    <!-- A working copy is normally an ongoing personal state rather than a staging area so the
    bar reads as neutral status. It appears only while one exists, and the same actions stay in the
    tab's menu since this is a shortcut rather than the only route to them. -->
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
// Clipped here rather than on the page because hiding an axis makes an element its own scrolling
// box, and a header inside one pins to that box instead of to the window.
.layout {
  overflow-x: hidden;
}

.addWidgetRow {
  padding: 4px 0;
}

// A floor rather than a fixed height since the minimum is set inline from where this page's
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

.draggedWidgetIcon {
  position: fixed;
  z-index: 5000;
  pointer-events: none;
}
</style>
