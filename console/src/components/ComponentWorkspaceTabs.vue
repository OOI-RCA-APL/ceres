<script lang="ts" setup>
import { useKeyModifier } from '@vueuse/core'
import { QMenu, QPopupEdit } from 'quasar'
import { nextTick, watch } from 'vue'

import { useAuth } from '@/api/auth'
import WorkspaceTabLabel from '@/components/WorkspaceTabLabel.vue'
import { useDialogs } from '@/dialogs'
import { isWorkspaceFile, useFileDrop } from '@/filedrop'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { isStructurallyEqual } from '@/utilities'
import {
  isWorkspaceWritable,
  useWorkspaces,
  withoutMeta,
  Workspace,
  WorkspaceEdit,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
} from '@/workspace'

const {
  workspaces,
  active,
  canManage,
  canCreate,
  openable = [],
  showPlacement = false,
  activeActions,
  activeState,
} = defineProps<{
  workspaces: Workspace[]
  active: string | null
  /** Workspaces placed here that the strip is not currently showing, offered by the add button. */
  openable?: Workspace[]
  /** Whether this strip mixes placements, which is what makes naming them on each tab useful. */
  showPlacement?: boolean
  /** Whether the caller may manage the component, which is what a shared workspace here follows. */
  canManage: boolean
  /** Whether the caller may add a workspace here, which needs only view since it lands private. */
  canCreate: boolean
  activeActions?: WorkspaceHeaderActions
  activeState?: WorkspaceHeaderState
}>()

const emit = defineEmits<{
  select: [id: string]
  close: [id: string]
  open: [id: string]
  create: []
  import: [files: File[]]
  reorder: [workspaces: Workspace[]]
}>()

const auth = useAuth()
const dialogs = useDialogs()
const workspaceStore = useWorkspaces()

// Dropping an exported workspace file onto the strip adds it to this component, the same as
// dropping a file onto a browser's tab bar opens it there.
const fileDrop = useFileDrop((files) => emit('import', files), isWorkspaceFile)

function isWritable(workspace: Workspace): boolean {
  return isWorkspaceWritable(workspace, auth.user?.id, canManage)
}

const isApple = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const undoShortcut = isApple ? '⌘Z' : 'Ctrl+Z'
const redoShortcut = isApple ? '⇧⌘Z' : 'Ctrl+Y'

// Tabs reorder by pointer rather than by the HTML5 drag API, so they behave the way browser tabs
// do. The same behavior drives the overview's workspace list, which is why it lives in a shared
// composable rather than here.
let rootElement = $ref<HTMLElement | null>(null)

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(rootElement?.querySelectorAll<HTMLElement>('.q-tab') ?? [])],
  onReorder: (from, to) => emit('reorder', moved([...workspaces], from, to)),
})

// The add button offers what is already here before making something new, the way a browser's new
// tab button opens a page of somewhere to go. Holding shift skips the picker, for anyone who knows
// they want a new one.
let picking = $ref(false)

const shiftHeld = useKeyModifier('Shift')

// The button says which of the two it is about to do. Layered pages for the picker, since what it
// opens is the other workspaces already here, and a plus once shift turns it into making a new
// one. The picker opens either way, so that creating is always reached the same way rather than
// the button quietly changing meaning once a strip happens to hold everything.
const opensPicker = $computed(() => shiftHeld.value !== true)

function onAddClick(event: MouseEvent) {
  if (event.shiftKey) {
    picking = false
    emit('create')
    return
  }

  picking = true
}

// One menu per tab, reachable from the dots and from a right-click on the tab. Held by workspace
// rather than by position, since dragging renumbers the strip.
const menus = new Map<string, QMenu>()

function setMenu(id: string, element: QMenu | null) {
  if (element == null) {
    menus.delete(id)
  } else {
    menus.set(id, element)
  }
}

function showMenu(id: string, event: Event) {
  menus.get(id)?.show(event)
}

function onTabClick(id: string) {
  if (reorder.consumeClick()) {
    return
  }

  emit('select', id)
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
  return edit != null && !isStructurallyEqual(withoutMeta(edit.data), withoutMeta(workspace.data))
}

// The active tab renames through the live workspace context so the same handler that persists
// the standalone header's rename keeps doing so here. The popup itself lives in this v-for, so
// its template ref comes back as an array rather than a single instance.
let renamePopup = $ref<QPopupEdit[]>([])
let renameDraft = $ref('')

async function openRename(workspace: Workspace) {
  if (workspace.id !== active) {
    return
  }

  // The popup snapshots its model when it opens, so the draft has to land before it is shown.
  renameDraft = workspace.name
  await nextTick()
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
        'never see it again. To remove it from your own tabs without deleting it, close the ' +
        'tab instead.' +
        '</i>',
    })
    .onOk(async () => {
      await workspaceStore.delete(workspace.id)
    })
}
</script>

<template>
  <div
    ref="rootElement"
    :class="[$style.root, fileDrop.active.value && $style.dropTarget, 'no-wrap', 'row']"
    data-workspace-drop="tabs"
    v-bind="canCreate ? fileDrop.handlers : {}"
  >
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
        :class="[
          $style.tab,
          reorder.isSwapping && $style.swapping,
          reorder.isDragging && $style.arranging,
          reorder.isHeld(index) && $style.held,
          reorder.isGrabbed(index) && $style.grabbed,
        ]"
        :name="workspace.id"
        :style="reorder.styleFor(index)"
        v-bind="reorder.handlers(index)"
        @click="onTabClick(workspace.id)"
      >
        <div
          :class="[$style.tabInner, 'items-center', 'no-wrap', 'row']"
          @dblclick.stop="openRename(workspace)"
        >
          <!-- A grip appears at the tab's leading edge on hover, so the strip says it can be
          arranged without spending width on a handle that is idle the rest of the time. The whole
          tab is still the drag target, and the grip is the hint. -->
          <span :class="$style.grip">
            <q-icon :name="icons.dragVertical" size="15px" />
          </span>
          <workspace-tab-label :show-placement="showPlacement" :workspace="workspace" />
          <q-popup-edit
            v-if="workspace.id === active"
            ref="renamePopup"
            v-slot="scope"
            v-model="renameDraft"
            anchor="bottom left"
            auto-save
            :class="$style.popupEdit"
            :cover="false"
            no-parent-event
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
            :class="hasWorkingCopy(workspace) && $style.editedRing"
            dense
            flat
            :icon="icons.more"
            round
            size="6.5px"
            :style="{ marginTop: '1px' }"
            @click.stop="showMenu(workspace.id, $event)"
            @mousedown.stop
            @touchstart.stop
          >
            <q-tooltip v-if="hasWorkingCopy(workspace)">
              This workspace has unsaved changes.
            </q-tooltip>
          </q-btn>
          <!-- One menu per tab, opened by the dots or by right-clicking the tab itself, which is
          where a context menu is looked for first. -->
          <q-menu :ref="(element: any) => setMenu(workspace.id, element)" context-menu>
            <q-card bordered flat>
              <q-list dense>
                <template
                  v-if="workspace.id === active && activeActions != null && activeState != null"
                >
                  <q-item v-close-popup clickable dense @click="emit('close', workspace.id)">
                    <q-item-section avatar>
                      <q-icon :name="icons.close" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-separator />
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
                  </template>
                </template>
                <template v-else>
                  <q-item v-close-popup clickable dense @click="emit('close', workspace.id)">
                    <q-item-section avatar>
                      <q-icon :name="icons.close" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-separator />
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
                  <template v-if="isWritable(workspace)">
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
          <q-btn
            class="faded-hover"
            :class="[$style.close, workspace.id === active && $style.closeShown]"
            dense
            flat
            :icon="icons.close"
            round
            size="6.5px"
            @click.stop="emit('close', workspace.id)"
            @mousedown.stop
            @touchstart.stop
          >
            <q-tooltip class="bg-primary text-white">Close Workspace</q-tooltip>
          </q-btn>
        </div>
      </q-tab>
    </q-tabs>
    <q-btn
      v-if="canCreate"
      :class="[$style.add, 'q-ml-xs']"
      dense
      flat
      :icon="opensPicker ? icons.workspaces : icons.add"
      round
      size="sm"
      @click="onAddClick"
    >
      <!-- Silent while the picker is open, since the menu it describes is already showing. -->
      <q-tooltip v-if="!picking" class="bg-primary text-white">
        {{ opensPicker ? 'Open a workspace, or hold shift to create one.' : 'Create a workspace.' }}
      </q-tooltip>
      <!-- Opened from the click handler alone, so holding shift can bypass it. Left to its own
      devices a menu inside a button opens on every click, shift or not. -->
      <q-menu
        v-model="picking"
        anchor="bottom left"
        no-parent-event
        :offset="[0, 4]"
        self="top left"
      >
        <q-card bordered flat>
          <q-list dense :style="{ maxHeight: '320px', overflowY: 'auto' }">
            <q-item-label :class="$style.menuHeader" header>Workspaces</q-item-label>
            <q-item v-if="openable.length === 0" dense>
              <q-item-section>
                <q-item-label class="text-grey-6">All of them are already open.</q-item-label>
              </q-item-section>
            </q-item>
            <q-item
              v-for="workspace in openable"
              :key="workspace.id"
              v-close-popup
              clickable
              dense
              @click="emit('open', workspace.id)"
            >
              <q-item-section avatar>
                <q-icon
                  :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ workspace.name }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <q-separator />
          <div class="q-pa-sm">
            <q-btn
              v-close-popup
              class="full-width"
              color="primary"
              dense
              :icon="icons.add"
              label="Create Workspace"
              no-caps
              outline
              @click="emit('create')"
            />
          </div>
        </q-card>
      </q-menu>
    </q-btn>
  </div>
</template>

<style lang="scss" module>
// Each tab carries the workspace icon so the group reads as workspaces rather than as page
// sections, and the selected one is marked by a filled block instead of an underline, which sits
// better in a header rail that already uses chips and icon buttons.

// The strip takes the full height of the header row it sits in and its tabs stretch to fill it,
// so the selected tab's fill runs from the top of the header into the separator beneath it, the
// way a tab is expected to meet the surface it belongs to.
// The strip takes the full height of the header row it sits in and its tabs stretch to fill it,
// so the selected tab's fill runs from the top of the header into the separator beneath it, the
// way a tab is expected to meet the surface it belongs to.
//
// The trailing space is where the picker sits. Reserving it rather than letting the button ride
// at the end of the row keeps the button in the same place however long the strip grows, and
// stops the tabs scrolling out from under it.
.root {
  position: relative;
  flex: 1;
  align-self: stretch;
  align-items: stretch;
  min-width: 0;
  padding-top: 4px;
  padding-right: 30px;
  overflow: hidden;
}

// An inset outline rather than a border, so the strip does not shift by a pixel when a file is
// dragged over it.
.dropTarget {
  box-shadow: inset 0 0 0 2px $primary;
  border-radius: 4px;
}

.tabs {
  height: 100%;
  min-width: 0;
}

// A strip that outgrows its container scrolls, the way a browser's tab bar does. Quasar's own
// answer is a pair of arrow buttons, which cost width in a header that has none to spare and are
// awkward next to tabs that are also draggable.
.tabs :global(.q-tabs__content) {
  overflow-x: auto;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

.tabs :global(.q-tabs__arrow) {
  display: none;
}

// Quasar's dense tabs force their own horizontal padding, so the tab's own spacing is carried by
// the row inside it instead of fighting that rule.
// The grip and the close button sit against the tab's own edges rather than inside the row, so
// they cost the same width whether they are showing or not and the label never moves under the
// pointer. Both are positioned against the tab itself, which means Quasar's own tab padding has
// to go, with the spacing carried by the row inside instead.
.tabInner {
  height: 100%;
  padding: 0 20px 0 19px;
}

// The grip's box runs from the tab's leading edge to the far side of the workspace icon, so the
// whole of that end reads as the place to take hold of, with the glyph itself sitting at the
// start of it. Zero opacity still answers the pointer, which is what carries the cursor before
// the grip has faded in.
.grip {
  position: absolute;
  z-index: 1;
  top: 50%;
  left: 2px;
  display: flex;
  align-items: center;
  // Reaches past the glyph to the far side of the workspace icon, so that whole end of the tab
  // carries the grab cursor. Zero opacity still answers the pointer, which is what carries the
  // cursor before the grip has faded in.
  width: 32px;
  cursor: grab;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.15s;
}

.tab:hover .grip {
  opacity: 0.7;
}

// Quasar's dense tabs impose a 36px minimum on the tab and pad its content box vertically, which
// together push the tab taller than the header it sits in. Both need matching specificity to
// override, so the minimum is cleared through the strip and the padding through the inner box.
.tabs .tab {
  height: 100%;
  min-height: 0;
  padding: 0;
}

.tab :global(.q-tab__content) {
  padding: 0;
}

.tab {
  border-radius: 4px 4px 0 0;
  opacity: 0.7;
  transition: background-color 0.2s, opacity 0.2s, transform 0.16s ease;
  touch-action: none;

  &:hover {
    opacity: 1;
  }

  &:global(.q-tab--active) {
    opacity: 1;
    background-color: $primary;
    color: white;
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

// A workspace with local changes rings its menu button rather than carrying an icon of its own.
// The ring is drawn as an outline so it takes no space, which keeps a tab exactly as wide edited
// as it is clean, and leaves the tab with one icon instead of two.
// A workspace with local changes rings its menu dots rather than carrying an icon of its own. The
// ring is drawn on the dots themselves so it sits tight against them and leaves the button's hit
// area alone, and being an outline it takes no space, keeping a tab exactly as wide edited as it
// is clean. Quasar buttons carry `no-outline`, which clears outlines with `!important`, so this
// has to be forced back on.
// The close button holds its place whether or not it is showing, so a tab stays exactly as wide
// hovered as it is at rest and the strip does not shuffle under the pointer. The selected tab
// keeps it visible, since that is the one most likely to be closed next.
// The extra pixel matches the nudge on the menu button beside it, so the two sit on one line.
.close {
  position: absolute;
  top: 50%;
  right: 4px;
  opacity: 0;
  transform: translateY(calc(-50% + 1px));
  transition: opacity 0.15s;
}

.tab:hover .close,
.closeShown {
  opacity: 1;
}

.editedRing :global(.q-icon) {
  border-radius: 50%;
  outline: 1px dotted currentColor !important;
  outline-offset: 0;
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

// While a drag is in progress the strip must not clip the lifted tab, and hover highlighting on
// the tabs sliding aside would read as a second thing happening at once.
.arranging {
  &:hover {
    opacity: inherit;
  }
}

.held {
  z-index: 2;
  opacity: 1;
}

// The held tab tracks the pointer directly, so it must not smooth its own movement. It regains
// the transition once released, which is what animates it into the gap.
.grabbed {
  cursor: grabbing;
  transition: background-color 0.2s, opacity 0.2s;
}

.swapping {
  transition: none;
}

// Quasar pads a list header for a full-size list, which towers over the dense items beneath it.
.menuHeader {
  padding: 6px 16px 2px;
  font-size: 11px;
  letter-spacing: 0.06em;
  opacity: 0.6;
  text-transform: uppercase;
}

// Pinned to the trailing edge of the strip rather than carried along by it, so it stays where it
// was however far the tabs scroll.
.add {
  position: absolute;
  top: 50%;
  right: 2px;
  z-index: 2;
  opacity: 0.7;
  transform: translateY(-50%);

  &:hover {
    opacity: 1;
  }
}
</style>
