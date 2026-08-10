<script lang="ts" setup>
import { QMenu } from 'quasar'

import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { moved, usePointerReorder } from '@/reorder'
import { useTabs } from '@/tabs'
import { inStandardOrder, isWorkspaceWritable, useWorkspaces, Workspace } from '@/workspace'

const { workspaces, openIds, placement, canManage } = defineProps<{
  /** Every workspace placed here that the caller can view, whether or not it is open. */
  workspaces: Workspace[]
  /** What the strip below is showing, reported by the tab icon on each row. */
  openIds: string[]
  placement: string
  /** Whether the caller may manage the placement, which the shared order follows. */
  canManage: boolean
}>()

const emit = defineEmits<{
  open: [id: string]
  /** A copy to put on the strip directly after the workspace it was copied from. */
  openBeside: [afterId: string, id: string]
  /** Taken off the strip, left to the page since closing what is showing has to move off it. */
  close: [id: string]
  /** Workspaces to copy a link to, which the page builds from its own placement. */
  share: [ids: string[]]
}>()

const auth = useAuth()
const dialogs = useDialogs()
const tabs = useTabs()
const workspaceStore = useWorkspaces()

const ordered = $computed(() => pending ?? inStandardOrder(workspaces))

// Read from the strip itself rather than worked out from the tab set since what the set means
// depends on the strip's defaults, which only the page holds. A home strip draws its defaults far
// more narrowly than the list here so the two disagree unless the strip is asked.
function isOpen(workspace: Workspace): boolean {
  return openIds.includes(workspace.id)
}

function isWritable(workspace: Workspace): boolean {
  return isWorkspaceWritable(workspace, auth.user?.id, canManage)
}

/** Where a workspace turned on from this list belongs in the strip.

Placed against its neighbours here rather than appended so the strip reads in the same order the
list does instead of recording whatever was turned on last. The nearest workspace above it that is
already showing takes it directly after, failing that the nearest one below takes it directly
before, and with neither showing it goes on the end.

The whole list is walked, shared before private, which is the order these rows appear in.
*/
function tabIndexFor(id: string): number {
  const listed = [...sharedWorkspaces, ...privateWorkspaces].map((workspace) => workspace.id)
  const at = listed.indexOf(id)

  for (let index = at - 1; index >= 0; index--) {
    const position = openIds.indexOf(listed[index])
    if (position >= 0) {
      return position + 1
    }
  }

  for (let index = at + 1; index < listed.length; index++) {
    const position = openIds.indexOf(listed[index])
    if (position >= 0) {
      return position
    }
  }

  return openIds.length
}

// Placing only ever puts a workspace on the strip. One already there keeps the position it has
// since clicking a row is a request to look at it rather than to rearrange the tabs around it.
async function openAsTab(workspace: Workspace) {
  if (isOpen(workspace)) {
    return
  }

  await tabs.openAt(placement, workspace.id, openIds, tabIndexFor(workspace.id))
}

// Putting a workspace on the strip or taking it off again, which is the same closing and opening
// the tabs themselves do. The workspace is untouched either way. Closing goes through the page
// because taking away the one being shown has to move off it as well.
async function toggleTab(workspace: Workspace) {
  if (isOpen(workspace)) {
    emit('close', workspace.id)
    return
  }

  await openAsTab(workspace)
}

async function open(workspace: Workspace, groupReorder: ReturnType<typeof usePointerReorder>) {
  // Releasing a drag must not also open what was dragged.
  if (groupReorder.consumeClick()) {
    return
  }

  await openAsTab(workspace)
  emit('open', workspace.id)
}

// A workspace opened on home keeps its placement so its widgets still resolve relative addresses
// against this component wherever it is being viewed from. Home lists its own workspaces the same
// way, where opening one on home is what the row above already does.
const isHome = $computed(() => placement === engineRoot)

async function openOnHome(workspace: Workspace) {
  await workspaceStore.open(workspace.id)
}

// Shared and private are listed apart rather than mixed because they answer different questions.
// The shared ones are what this component offers everyone who can see it, and the private ones are
// the caller's own work on it, which nobody else has.
const sharedWorkspaces = $computed(() => ordered.filter((workspace) => workspace.owner_id == null))
const privateWorkspaces = $computed(() => ordered.filter((workspace) => workspace.owner_id != null))

// The standard order is what a user sees before they have arranged this strip themselves so it is
// shared and only a manager may change it. Dragging a tab arranges one person's own strip, which
// is why the shared order is dragged here instead. A private workspace is nobody else's to see, so
// its owner arranges it whatever their access to the component.
let root = $ref<HTMLElement | null>(null)

// Rows drag exactly as tabs do, down the list rather than across it. Held while the write is in
// flight so the list does not snap back to the old order and then forward again once it lands.
let pending = $ref<Workspace[] | null>(null)

function rowsOf(group: string): HTMLElement[] {
  const selector = `[data-workspace-group="${group}"]`
  return [...(root?.querySelectorAll<HTMLElement>(selector) ?? [])]
}

const sharedReorder = usePointerReorder({
  axis: 'vertical',
  elements: () => rowsOf('shared'),
  onReorder: (from, to) =>
    void persistOrder(moved(sharedWorkspaces, from, to), privateWorkspaces as Workspace[]),
  onDrop: (index, event) => onDrop(sharedWorkspaces[index], 'shared', event),
})

const privateReorder = usePointerReorder({
  axis: 'vertical',
  elements: () => rowsOf('private'),
  onReorder: (from, to) =>
    void persistOrder(sharedWorkspaces as Workspace[], moved(privateWorkspaces, from, to)),
  onDrop: (index, event) => onDrop(privateWorkspaces[index], 'private', event),
})

/** Take a row released outside its own group, which is either the other group or the tab strip.

Returns whether the drop was claimed, which stops the release from reordering the source group.
*/
function onDrop(workspace: Workspace, from: 'shared' | 'private', event: PointerEvent): boolean {
  const element = document.elementFromPoint(event.clientX, event.clientY)
  if (element == null) {
    return false
  }

  if (element.closest('[data-workspace-drop="tabs"]') != null) {
    void openAsTab(workspace).then(() => emit('open', workspace.id))
    return true
  }

  const list = element.closest('[data-workspace-group-list]')
  const to = list?.getAttribute('data-workspace-group-list')
  if (to == null || to === from || (to !== 'shared' && to !== 'private')) {
    return false
  }

  // Publishing a workspace shows it to everyone who can see the placement so that direction is a
  // manager's to make either way. Taking a copy private only ever creates the caller's own
  // workspace so it needs nothing beyond being able to see the original.
  if (to === 'shared' && !canManage) {
    return true
  }

  dialogs.transferWorkspace(workspace, to, canManage).onOk((mode: 'copy' | 'move') => {
    void transfer(workspace, to, mode)
  })

  return true
}

async function transfer(workspace: Workspace, to: 'shared' | 'private', mode: 'copy' | 'move') {
  const owner = to === 'private' ? auth.user?.id ?? null : null

  if (mode === 'copy') {
    await workspaceStore.create({
      name: workspace.name,
      scope: workspace.scope,
      owner_id: owner,
      data: workspace.data,
    })
    return
  }

  await workspaceStore.update(workspace.id, { owner_id: owner })
}

// One menu per row, reachable from the dots and from a right-click on the row. Held by workspace
// rather than by position since the two groups renumber independently.
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

// Renaming happens on the row itself rather than in a dialog, the same as renaming a tab, so the
// name is edited where it is read.
let editingId = $ref<string | null>(null)

// Renaming a workspace changes it for everybody who can see it so it takes the same write access
// deleting does rather than being offered to anyone who can merely look at it.
function openRename(workspace: Workspace) {
  if (!isWritable(workspace)) {
    return
  }

  editingId = workspace.id
}

const { shift: shiftHeld } = useModifiers()

/** Which row is showing its name as a field, whether offered or being typed into.

Holding shift over a row turns its name into a field there and then so the rename is offered
rather than hidden behind a shortcut nobody would guess. Clicking into it makes it a real edit
that survives shift being released.
*/
let hoveredId = $ref<string | null>(null)

// Reported by the name rather than by the row so the offer belongs to the text being renamed.
// Leaving only clears what it was set to since the pointer can reach the next name before the one
// it left says it has been left.
function setNameHovered(workspace: Workspace, hovered: boolean) {
  if (hovered) {
    hoveredId = workspace.id
  } else if (hoveredId === workspace.id) {
    hoveredId = null
  }
}

function isNaming(workspace: Workspace): boolean {
  if (editingId === workspace.id) {
    return true
  }

  return shiftHeld.value && hoveredId === workspace.id && isWritable(workspace)
}

async function rename(workspace: Workspace, value: string) {
  await workspaceStore.rename(workspace.id, value)
}

// Adding from a group's own heading opens the usual dialog, already set to the kind of workspace
// that group holds so the one question the dialog would ask is answered by where it was started
// from. What comes back goes onto the strip and is shown.
function create(group: 'shared' | 'private') {
  dialogs.createWorkspace(placement, group === 'private').onOk(async (created: Workspace) => {
    await tabs.open(placement, created.id)
    emit('open', created.id)
  })
}

const groups = $computed(() => [
  {
    key: 'shared',
    label: 'Shared',
    items: sharedWorkspaces,
    reorder: sharedReorder,
    canReorder: canManage,
    // A shared workspace shows up for everyone who can see the component so adding one takes
    // manage. A private one is nobody else's to see so it only takes being able to look here.
    canAdd: canManage,
  },
  {
    key: 'private',
    label: 'Private',
    items: privateWorkspaces,
    reorder: privateReorder,
    canReorder: true,
    canAdd: true,
  },
])

// Each group is positioned within itself so a private workspace never has to be ordered against a
// shared one it is never listed beside.
async function persistOrder(shared: Workspace[], owned: Workspace[]) {
  pending = [...shared, ...owned]

  // Every position is rewritten rather than just the pair that moved because a workspace that has
  // never been positioned has no order at all and would otherwise keep sorting last.
  const positions = [...shared.entries(), ...owned.entries()]

  try {
    await Promise.all(
      positions.map(([index, candidate]) =>
        candidate.data.meta.order === index
          ? Promise.resolve()
          : workspaceStore.update(candidate.id, {
              data: { ...candidate.data, meta: { ...candidate.data.meta, order: index } },
            })
      )
    )
  } finally {
    pending = null
  }
}

function openSettings(workspace: Workspace) {
  dialogs.workspaceSettings(workspace.id).onOk(() => workspaceStore.refresh())
}

function duplicate(workspace: Workspace) {
  dialogs.duplicateWorkspace(workspace.id, workspace.data).onOk((created: Workspace) => {
    emit('openBeside', workspace.id, created.id)
  })
}

function promptDelete(workspace: Workspace) {
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
  <div ref="root">
    <div class="q-mb-xs text-subtitle2">Workspaces</div>
    <template v-for="group in groups" :key="group.key">
      <!-- A group the caller may add to keeps its heading even while it is empty since that
      heading is where the first one is made from. -->
      <div v-if="group.items.length > 0 || group.canAdd" :class="$style.group">
        <div :class="[$style.groupHeader, 'items-center', 'row']">
          <div class="text-grey-6" :class="$style.groupLabel">{{ group.label }}</div>
          <q-space />
          <q-btn
            v-if="group.canAdd"
            :class="$style.add"
            dense
            flat
            :icon="icons.add"
            round
            size="8px"
            @click="create(group.key as 'shared' | 'private')"
          >
            <q-tooltip
              anchor="center left"
              class="bg-primary text-white"
              :offset="[4, 0]"
              self="center right"
            >
              Create {{ group.label }} Workspace
            </q-tooltip>
          </q-btn>
        </div>
        <div
          v-if="group.items.length === 0"
          class="text-grey-6"
          :class="$style.empty"
          :data-workspace-group-list="group.key"
        >
          None yet.
        </div>
        <q-list
          v-else
          bordered
          class="rounded-borders"
          :data-workspace-group-list="group.key"
          dense
          separator
        >
          <q-item
            v-for="(workspace, index) in group.items"
            :key="workspace.id"
            :class="[
              $style.row,
              group.reorder.isSwapping && $style.swapping,
              group.reorder.isDragging && $style.arranging,
              group.reorder.isHeld(index) && $style.held,
              group.reorder.isGrabbed(index) && $style.grabbed,
            ]"
            clickable
            :data-workspace-group="group.key"
            :style="group.reorder.styleFor(index)"
            v-bind="group.canReorder ? group.reorder.handlers(index) : {}"
            @click="open(workspace, group.reorder)"
          >
            <!-- A grip appears at the row's leading edge on hover so a draggable row says so
            without spending a column on a handle that is idle the rest of the time. The whole row
            is still the drag target, and the grip is the hint. -->
            <span v-if="group.canReorder" :class="$style.grip">
              <q-icon :name="icons.dragVertical" size="17px" />
            </span>
            <q-item-section avatar>
              <q-icon
                :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
                size="18px"
              />
            </q-item-section>
            <q-item-section @dblclick.stop="openRename(workspace)">
              <q-item-label>
                <!-- The name alone reports being hovered. Holding shift over a row offers to
                rename it, and the offer belongs to the text being renamed rather than to the whole
                row. -->
                <span
                  :class="$style.name"
                  @mouseenter="setNameHovered(workspace, true)"
                  @mouseleave="setNameHovered(workspace, false)"
                >
                  <inline-name-edit
                    :claim="editingId === workspace.id"
                    :editing="isNaming(workspace)"
                    :name="workspace.name"
                    @rename="(value: string) => rename(workspace, value)"
                    @update:editing="(value: boolean) => (editingId = value ? workspace.id : null)"
                  />
                </span>
              </q-item-label>
            </q-item-section>
            <!-- The tab icon both says whether this workspace is on the strip below and puts it
            there or takes it away, filled while it is showing and hollow while it is not. -->
            <q-item-section side>
              <q-btn
                dense
                flat
                :icon="isOpen(workspace) ? icons.tab : icons.tabUnselected"
                round
                size="8px"
                @click.stop="toggleTab(workspace)"
              >
                <q-tooltip class="bg-primary text-white" :delay="500">Toggle Tab</q-tooltip>
              </q-btn>
            </q-item-section>
            <q-item-section side>
              <q-btn
                dense
                flat
                :icon="icons.more"
                round
                size="8px"
                @click.stop="showMenu(workspace.id, $event)"
              />
            </q-item-section>
            <!-- One menu per row, opened by the dots or by right-clicking the row itself, which
            is where a context menu is looked for first. -->
            <q-menu
              :ref="(element: any) => setMenu(workspace.id, element)"
              context-menu
              @before-show="group.reorder.consumeClick()"
            >
              <q-card bordered flat>
                <q-list dense>
                  <q-item v-close-popup clickable dense @click="open(workspace, group.reorder)">
                    <q-item-section avatar>
                      <q-icon :name="icons.workspace" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Open</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item
                    v-if="!isHome"
                    v-close-popup
                    clickable
                    dense
                    @click="openOnHome(workspace)"
                  >
                    <q-item-section avatar>
                      <q-icon :name="icons.open" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Open on Home</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-separator />
                  <q-item
                    v-if="isWritable(workspace)"
                    v-close-popup
                    clickable
                    dense
                    @click="openRename(workspace)"
                  >
                    <q-item-section avatar>
                      <q-icon :name="icons.rename" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Rename</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable dense @click="openSettings(workspace)">
                    <q-item-section avatar>
                      <q-icon :name="icons.settings" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Settings</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable dense @click="emit('share', [workspace.id])">
                    <q-item-section avatar>
                      <q-icon :name="icons.share" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Copy Link</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable dense @click="duplicate(workspace)">
                    <q-item-section avatar>
                      <q-icon :name="icons.duplicate" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Duplicate</q-item-label>
                    </q-item-section>
                  </q-item>
                  <template v-if="isWritable(workspace)">
                    <q-separator />
                    <q-item v-close-popup clickable dense @click="promptDelete(workspace)">
                      <q-item-section avatar>
                        <q-icon :name="icons.delete" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Delete</q-item-label>
                      </q-item-section>
                    </q-item>
                  </template>
                </q-list>
              </q-card>
            </q-menu>
          </q-item>
        </q-list>
      </div>
    </template>
  </div>
</template>

<style lang="scss" module>
.empty {
  padding: 4px 0;
}

.group + .group {
  margin-top: 10px;
}

// The heading carries its own add button so a workspace is made in the group it belongs to and
// nothing has to ask afterwards whether it is shared or private.
.groupHeader {
  margin-bottom: 2px;
  min-height: 20px;
}

.groupLabel {
  font-size: 12px;
}

// Held off the trailing edge by the same padding a row gives its own menu button so this button
// sits on the same vertical line as the dots in the list beneath it.
.add {
  margin-right: 16px;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.group:hover .add,
.add:hover {
  opacity: 1;
}

// The grip sits in the row's leading padding rather than in its content so it costs the same
// width whether it is showing or not and nothing moves under the pointer.
// Doubled so this wins over Quasar's own item padding, which is set on a single class too. The
// extra leading space is where the grip sits so it never lands on the workspace icon.
.row.row {
  position: relative;
  padding-left: 22px;
  transition: background-color 0.2s, transform 0.16s ease;
  touch-action: none;
}

// Hugs the name so hovering the stretch of empty row beside it is not hovering the name.
.name {
  align-self: flex-start;
}

// The grip's box runs from the row's leading edge to the far side of the workspace icon so that
// whole end reads as the place to take hold of. Zero opacity still receives the pointer,
// carrying the cursor before the grip fades in.
.grip {
  position: absolute;
  top: 50%;
  left: 2px;
  z-index: 1;
  display: flex;
  align-items: center;
  // Reaches past the glyph to the far side of the workspace icon so that whole end of the row
  // carries the grab cursor.
  width: 38px;
  cursor: grab;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.15s;
}

.row:hover .grip {
  opacity: 0.7;
}

// While a drag is in progress the list must not clip the lifted row, and hover highlighting on the
// rows sliding aside would read as a second thing happening at once.
.arranging:hover {
  background: inherit;
}

// The lifted row sits above the ones sliding under it so it takes the surface it was lifted off
// rather than letting them show through, and thins slightly to read as held.
.held {
  z-index: 2;
  position: relative;
  opacity: 0.92;
}

:global(.dark) .held {
  background: $dark;
}

:global(.light) .held {
  background: white;
}

// The held row tracks the pointer directly so it must not smooth its own movement. The
// transition returns on release and animates it into the gap.
.grabbed {
  cursor: grabbing;
  transition: background-color 0.2s;
}

.swapping {
  transition: none;
}
</style>
