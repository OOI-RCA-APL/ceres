<script lang="ts" setup>
import { QPopupEdit } from 'quasar'
import { nextTick, watch } from 'vue'

import { useAuth } from '@/api/auth'
import { useDialogs } from '@/dialogs'
import { isWorkspaceFile, useFileDrop } from '@/filedrop'
import icons from '@/icons'
import { isStructurallyEqual } from '@/utilities'
import {
  useWorkspaces,
  withoutMeta,
  Workspace,
  WorkspaceEdit,
  WorkspaceHeaderActions,
  WorkspaceHeaderState,
} from '@/workspace'

const { workspaces, active, canManage, canCreate, activeActions, activeState } = defineProps<{
  workspaces: Workspace[]
  active: string | null
  /** Whether the caller may manage the component, which is what a shared workspace here follows. */
  canManage: boolean
  /** Whether the caller may add a workspace here, which needs only view since it lands private. */
  canCreate: boolean
  activeActions?: WorkspaceHeaderActions
  activeState?: WorkspaceHeaderState
}>()

const emit = defineEmits<{
  select: [id: string]
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

// A private workspace belongs to its owner alone, so they may edit and delete it whatever their
// access on the component. A shared one follows the component.
function isWritable(workspace: Workspace): boolean {
  if (workspace.owner_id != null) {
    return workspace.owner_id === auth.user?.id
  }

  return canManage
}

const isApple = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
const undoShortcut = isApple ? '⌘Z' : 'Ctrl+Z'
const redoShortcut = isApple ? '⇧⌘Z' : 'Ctrl+Y'

// Tabs reorder by pointer rather than by the HTML5 drag API, so they behave the way browser tabs
// do. The held tab tracks the pointer, its neighbours slide aside as it passes their midpoints,
// and it settles into the gap when released. Positions are measured once when the drag begins and
// every offset is derived from those, so nothing depends on layout that is mid-animation.
type TabDrag = {
  index: number
  pointerId: number
  startX: number
  positions: { left: number; width: number }[]
  moved: boolean
}

const dragThreshold = 4
const settleDuration = 140

let rootElement = $ref<HTMLElement | null>(null)
let drag = $ref<TabDrag | null>(null)
let dragOffset = $ref(0)
let dragTarget = $ref(0)
let settling = $ref(false)
let swapping = $ref(false)
let suppressClick = false

function onPointerDown(index: number, event: PointerEvent) {
  suppressClick = false

  // The tab's own menu button owns its presses, and a drag should only ever start from a plain
  // left press.
  if (event.button !== 0 || (event.target as HTMLElement).closest('button') != null) {
    return
  }

  const elements = rootElement?.querySelectorAll<HTMLElement>('.q-tab') ?? []
  const positions = [...elements].map((element) => {
    const box = element.getBoundingClientRect()
    return { left: box.left, width: box.width }
  })

  if (positions.length !== workspaces.length) {
    return
  }

  drag = { index, pointerId: event.pointerId, startX: event.clientX, positions, moved: false }
  dragOffset = 0
  dragTarget = index
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (drag == null || event.pointerId !== drag.pointerId || settling) {
    return
  }

  const delta = event.clientX - drag.startX
  if (!drag.moved && Math.abs(delta) < dragThreshold) {
    return
  }

  drag.moved = true
  dragOffset = delta
  dragTarget = resolveTarget(delta)
}

/** Return the index the held tab would land on, given how far it has travelled. */
function resolveTarget(delta: number): number {
  if (drag == null) {
    return 0
  }

  const { index, positions } = drag
  const center = positions[index].left + positions[index].width / 2 + delta

  let target = index
  while (target > 0 && center < positions[target - 1].left + positions[target - 1].width / 2) {
    target--
  }
  while (
    target < positions.length - 1 &&
    center > positions[target + 1].left + positions[target + 1].width / 2
  ) {
    target++
  }

  return target
}

/** Return how far a tab slides aside to open the gap the held tab is heading for. */
function tabShift(index: number): number {
  if (drag == null || index === drag.index) {
    return 0
  }

  const width = drag.positions[drag.index].width
  if (drag.index < dragTarget && index > drag.index && index <= dragTarget) {
    return -width
  }
  if (drag.index > dragTarget && index >= dragTarget && index < drag.index) {
    return width
  }

  return 0
}

/** Return where the held tab comes to rest, which is the near edge of the gap it opened. */
function settledOffset(): number {
  if (drag == null) {
    return 0
  }

  const { index, positions } = drag
  if (dragTarget > index) {
    const target = positions[dragTarget]
    const held = positions[index]
    return target.left + target.width - (held.left + held.width)
  }
  if (dragTarget < index) {
    return positions[dragTarget].left - positions[index].left
  }

  return 0
}

function tabStyle(index: number) {
  if (drag == null) {
    return undefined
  }

  if (index === drag.index) {
    return { transform: `translateX(${settling ? settledOffset() : dragOffset}px)` }
  }

  return { transform: `translateX(${tabShift(index)}px)` }
}

async function onPointerUp(event: PointerEvent) {
  if (drag == null || event.pointerId !== drag.pointerId) {
    return
  }

  if (!drag.moved) {
    drag = null
    return
  }

  const { index } = drag
  const target = dragTarget

  // Let the held tab travel into its gap before the list reorders underneath it, otherwise it
  // jumps the remaining distance the instant the transform is dropped.
  suppressClick = true
  settling = true
  await new Promise((resolve) => setTimeout(resolve, settleDuration))

  // Dropping the offsets and reordering the list happen in the same frame, and the tabs that slid
  // aside are already standing where the new order puts them. Animating that frame would replay
  // the slide they just finished, so transitions are off across the swap and restored after the
  // browser has painted it.
  settling = false
  swapping = true
  drag = null
  dragOffset = 0

  if (target !== index) {
    const reordered = [...workspaces]
    const [moved] = reordered.splice(index, 1)
    reordered.splice(target, 0, moved)
    emit('reorder', reordered)
  }

  await nextTick()
  requestAnimationFrame(() => requestAnimationFrame(() => (swapping = false)))
}

function onTabClick(id: string) {
  if (suppressClick) {
    suppressClick = false
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
        'never see it again.' +
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
          swapping && $style.swapping,
          drag != null && $style.arranging,
          drag?.index === index && $style.held,
          drag?.index === index && !settling && $style.grabbed,
        ]"
        :name="workspace.id"
        :style="tabStyle(index)"
        @click="onTabClick(workspace.id)"
        @pointercancel="onPointerUp"
        @pointerdown="onPointerDown(index, $event)"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
      >
        <div :class="[$style.tabInner, 'items-center', 'no-wrap', 'row']">
          <!-- The leading icon already answers what kind of tab this is, so marking a private
          workspace here costs no width and adds no second icon to the tab. -->
          <q-icon
            :class="$style.tabIcon"
            :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
          >
            <q-tooltip v-if="workspace.owner_id != null" :delay="1000">
              This workspace is private to you.
            </q-tooltip>
          </q-icon>
          <span :class="$style.label" @dblclick.stop="openRename(workspace)">
            {{ workspace.name }}
          </span>
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
            @click.stop
            @mousedown.stop
            @touchstart.stop
          >
            <q-tooltip v-if="hasWorkingCopy(workspace)">
              This workspace has unsaved changes.
            </q-tooltip>
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
          </q-btn>
        </div>
      </q-tab>
    </q-tabs>
    <q-btn
      v-if="canCreate"
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
// sections, and the selected one is marked by a filled block instead of an underline, which sits
// better in a header rail that already uses chips and icon buttons.

// The strip takes the full height of the header row it sits in and its tabs stretch to fill it,
// so the selected tab's fill runs from the top of the header into the separator beneath it, the
// way a tab is expected to meet the surface it belongs to.
.root {
  align-self: stretch;
  align-items: stretch;
  padding-top: 4px;
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
}

// Quasar's dense tabs force their own horizontal padding, so the tab's own spacing is carried by
// the row inside it instead of fighting that rule.
.tabInner {
  height: 100%;
  padding: 0 6px 0 8px;
}

// Quasar's dense tabs impose a 36px minimum on the tab and pad its content box vertically, which
// together push the tab taller than the header it sits in. Both need matching specificity to
// override, so the minimum is cleared through the strip and the padding through the inner box.
.tabs .tab {
  height: 100%;
  min-height: 0;
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

.add {
  align-self: center;
  opacity: 0.7;

  &:hover {
    opacity: 1;
  }
}
</style>
