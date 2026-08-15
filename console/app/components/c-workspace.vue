<script lang="ts" setup>
import { useElementBounding, useEventListener, useMouse } from '@vueuse/core'
import { computed, nextTick, reactive, watch, watchEffect } from 'vue'

import { appHeaderHeight, densePageHeaderHeight } from '@/components/c-full-page.vue'
import CWorkspaceLayout from '@/components/c-workspace-layout.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { deepClone } from '@/utilities'
import { provideWidgetDrop } from '@/widget-drop'
import {
  provideWorkspace,
  rootLayoutId,
  type Widget,
  widgetInfos,
  type WidgetPlacement,
  type WorkspaceData,
  type WorkspaceHeaderActions,
  type WorkspaceHeaderState,
} from '@/workspace'

const {
  id,
  stickyTop,
  stripDocked = false,
} = defineProps<{
  id: string

  /** Where the host's tab strip pins, which the scroll room below the widgets is measured
  from. */
  stickyTop?: number

  /** Whether the host's tab strip is resting at the bottom edge, where the floating action
  bar would sit, so the bar yields to it. */
  stripDocked?: boolean
}>()

const emit = defineEmits<{
  /** A copy, for the page hosting this one to place beside the workspace it was copied from. */
  duplicated: [afterId: string, id: string]
}>()

const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()

const workspace = provideWorkspace(computed(() => id))

let original = $ref<WorkspaceData | null>(null)
const isViewingOriginal = $computed(() => original != null)

// Exposed to the hosting page, whose tab strip is the only place these are reached from. This
// component draws the widgets and nothing around them.
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
  startViewingOriginal: () => void startViewingOriginal(),
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

// Lets a host land a widget on this workspace's live working copy and drive the tab strip it
// renders for this component.
defineExpose({
  insertWidget: workspace.insertWidget,
  insertWidgetsAt: workspace.insertWidgetsAt,
  startInsertDrag,
  revealWidgets,
  headerActions,
  headerState: $$(headerState),
})

/** Put widgets built outside the workspace in hand, so the pointer already down starts the
same drag a widget's own header would. `drop` takes the release. */
function startInsertDrag(widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) {
  if (widgets.length === 0 || !workspace.canEdit) {
    return
  }

  workspace.drag = { widget: widgets[0] as Widget, widgets, layout: rootLayoutId, drop }
}

/** Select widgets a host just landed and scroll the first into view, which is the feedback
for the insert. */
async function revealWidgets(ids: string[]) {
  const [first, ...rest] = ids
  if (first == null) {
    return
  }

  workspace.selectWidget(first)
  for (const widgetId of rest) {
    workspace.selectWidget(widgetId, 'toggle')
  }

  await nextTick()
  document
    .querySelector(`[data-widget-id="${first}"]`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

void workspace.load()

// One viewport below where the tab strip pins. That is the least this component can be and still
// let the strip reach its pinned position, and it does not depend on how tall any one workspace
// is so every workspace on a strip can be scrolled the same distance.
const bottomRoom = $computed(
  () => `calc(100vh - ${(stickyTop ?? appHeaderHeight) + densePageHeaderHeight + 1}px)`,
)

const layoutView = $ref<InstanceType<typeof CWorkspaceLayout> | null>(null)

/** The box the widgets are laid out in, which a drag is measured against. */
const layoutElement = $computed(() => layoutView?.element ?? null)

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

let name = $ref<string>(workspace.name ?? '')
watch(
  () => name,
  async () => {
    // Switching workspaces reseeds this from the newly loaded one, which must not be mistaken
    // for the user having renamed anything.
    if (name === workspace.name) {
      return
    }

    await workspace.rename(name)
  },
)
watch(
  () => workspace.name,
  () => {
    if (workspace.name != null) {
      name = workspace.name
    }
  },
  { immediate: true },
)

// Started here and reached by every layout drawn under this component since a carousel slide is
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
    const pressed = event.key.toLowerCase()
    if (pressed === 'z' && !event.shiftKey) {
      event.preventDefault()
      workspace.undo()
    } else if ((pressed === 'z' && event.shiftKey) || pressed === 'y') {
      event.preventDefault()
      workspace.redo()
    } else if (pressed === 'g' && workspace.selection.length > 0) {
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

const addWidgetItems = $computed(() =>
  Object.values(widgetInfos).map((info) => ({
    label: info.name,
    onSelect: () => {
      workspace.addWidget(info.type, data?.layout.length ?? 0)
    },
  })),
)

function duplicate() {
  dialogs.duplicateWorkspace(id, data as WorkspaceData).onOk((created) => {
    emit('duplicated', id, created.id)
  })
}

function exportFile() {
  void workspace.exportFile()
}

function openSettings() {
  dialogs.workspaceSettings(id).onOk(() => workspace.refresh())
}

function promptDelete() {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message: `Are you sure you'd like to delete workspace "${workspace.name}"?`,
      note:
        'This action cannot be undone. You and any users with access to this workspace will ' +
        'never see it again.',
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
      message: `Commit changes to workspace "${workspace.name}"?`,
      note:
        'This will update the current shared version of this workspace, allowing users with ' +
        'access to see this version.',
      okLabel: 'Commit',
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
      message: 'Revert all personal changes to this workspace?',
      note:
        'This will discard your current working copy and replace it with the latest shared ' +
        'version of the workspace. The workspace will not be modified for any other users.',
      okLabel: 'Yes',
      okColor: 'warning',
    })
    .onOk(async () => {
      await workspace.revert()
      original = null
      key++
    })
}
</script>

<template>
  <c-full-page no-header>
    <div
      v-if="drop.active && workspace.drag != null"
      key="dragged-widget-icon"
      class="pointer-events-none fixed z-[5000]"
      :style="draggedWidgetIconStyle"
    >
      <div class="flex items-center rounded-md border border-default bg-elevated px-1">
        <c-text variant="th">
          {{ workspace.drag.widget.name }}
        </c-text>
        <c-badge
          v-if="workspace.drag.widgets.length > 1"
          class="ml-1"
          color="primary"
          :label="`+${workspace.drag.widgets.length - 1}`"
          size="sm"
        />
      </div>
    </div>
    <div
      :key="key"
      class="overflow-x-hidden px-2"
      :style="isViewingOriginal ? { border: '1px dashed var(--ui-warning)' } : undefined"
    >
      <div v-if="workspace.loading" class="py-6" />
      <div v-else-if="data == null" class="py-6 text-center">
        <c-text variant="body1">No workspace named "{{ name }}" exists.</c-text>
      </div>
      <c-workspace-layout v-else ref="layoutView" :layout="data.layout" :layout-id="rootLayoutId" />
    </div>
    <!-- Mounted only while showing so its remembered choices are read fresh each time. -->
    <c-workspace-widget-group-dialog
      v-if="groupDialogIds != null"
      :widget-ids="groupDialogIds"
      @close="groupDialogIds = null"
    />
    <!-- Held back while the layout is empty since a layout with nothing on it offers this same
    button in the middle of itself and two of it on screen at once is one too many. -->
    <div
      v-if="!isViewingOriginal && data != null && data.layout.length > 0"
      class="mt-2 flex items-center justify-center py-1"
    >
      <c-dropdown-menu :items="addWidgetItems">
        <c-tooltip text="Add Widget">
          <c-button aria-label="Add Widget" class="rounded-full" :icon="icons.add" size="xs" />
        </c-tooltip>
      </c-dropdown-menu>
    </div>
    <!-- Room below the widgets so the tab strip can always be scrolled to where it pins. A
    shorter workspace could not pin the strip, and switching to it from a taller one would drop
    the strip back down the page as the document shrank. -->
    <div class="h-[250px]" :style="{ minHeight: bottomRoom }" />
    <!-- A working copy is normally an ongoing personal state rather than a staging area so the
    bar reads as neutral status. It appears only while one exists, and the same actions stay in the
    tab's menu since this is a shortcut rather than the only route to them. -->
    <div
      v-if="workspace.edited && !stripDocked"
      class="flex items-center"
      :class="$style.actionBar"
      :style="actionBarStyle"
    >
      <template v-if="isViewingOriginal">
        <c-tooltip text="Revert to Original Version">
          <c-button
            color="warning"
            :icon="icons.revertToOriginal"
            size="xs"
            variant="ghost"
            @click="promptRevert()"
          />
        </c-tooltip>
        <c-tooltip text="Stop Viewing Original">
          <c-button
            color="neutral"
            :icon="icons.close"
            size="xs"
            variant="ghost"
            @click="stopViewingOriginal()"
          />
        </c-tooltip>
      </template>
      <template v-else>
        <c-tooltip text="View Original">
          <c-button
            color="neutral"
            :icon="icons.viewOriginal"
            size="xs"
            variant="ghost"
            @click="startViewingOriginal()"
          />
        </c-tooltip>
        <c-tooltip text="Commit Changes">
          <c-button
            color="primary"
            :disabled="!workspace.canEdit"
            :icon="icons.confirm"
            size="xs"
            @click="promptCommit()"
          />
        </c-tooltip>
      </template>
    </div>
  </c-full-page>
</template>

<style module>
/* Rests on the bottom edge of the window, rounded only where it meets the page. Sticky would pin
it only while the page scrolls, and a short workspace does not, which would drop the bar below
the fold exactly when there is least reason to hunt for it. Its horizontal position is set
inline, from the widgets it acts on, and faded until reached for so it sits over the widgets
without demanding attention. */
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
  opacity: 0.85;
  transition: opacity 0.15s;
  background-color: #ffffffd9;
  box-shadow: 0 2px 10px #00000033;
}

:global(.dark) .actionBar {
  background-color: #000000a6;
  box-shadow: 0 2px 10px #00000080;
}

.actionBar:hover,
.actionBar:focus-within {
  opacity: 1;
}
</style>
