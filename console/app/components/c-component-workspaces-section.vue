<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { createReusableTemplate, useEventListener } from '@vueuse/core'
import { watch } from 'vue'

import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { useNotify } from '@/notify'
import { moved, usePointerReorder } from '@/reorder'
import { useTabs } from '@/tabs'
import { inStandardOrder, isWorkspaceWritable, useWorkspaces, type Workspace } from '@/workspace'

const {
  workspaces,
  openIds,
  placement,
  canManage,
  collapsible = false,
} = defineProps<{
  /** Every workspace placed here that the caller can view, whether or not it is open. */
  workspaces: Workspace[]
  /** What the strip below is showing, reported by the tab icon on each row. */
  openIds: string[]
  placement: string
  /** Whether the caller may manage the placement, which the shared order follows. */
  canManage: boolean
  /** Renders the section as an expansion item like the other detail sections, with the
  `expanded` model carrying its state. */
  collapsible?: boolean
}>()

let expanded = $(defineModel<boolean>('expanded', { default: true }))

// The groups render inside the expansion item or under the plain heading.
const [DefineGroups, ReuseGroups] = createReusableTemplate()

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
const notify = useNotify()
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
    const position = openIds.indexOf(listed[index] as string)
    if (position >= 0) {
      return position + 1
    }
  }

  for (let index = at + 1; index < listed.length; index++) {
    const position = openIds.indexOf(listed[index] as string)
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
  onDrop: (index, event) => onDrop(sharedWorkspaces[index] as Workspace, 'shared', event),
})

const privateReorder = usePointerReorder({
  axis: 'vertical',
  elements: () => rowsOf('private'),
  onReorder: (from, to) =>
    void persistOrder(sharedWorkspaces as Workspace[], moved(privateWorkspaces, from, to)),
  onDrop: (index, event) => onDrop(privateWorkspaces[index] as Workspace, 'private', event),
})

/** Whether a group takes the row travelling from the other one, which is when it says so.

Publishing takes manage on the placement, so without it the shared group never offers.
*/
function isDropTarget(key: string): boolean {
  if (key === 'shared') {
    return privateReorder.isMoving && canManage
  }

  return sharedReorder.isMoving
}

// Which group the pointer is over while a row travels. The offer stays faint until the row is
// actually over it, so carrying one into a group and out again lights nothing up behind it.
let hoveredGroup = $ref<string | null>(null)

// Measured once per drag rather than per move, since a rect read between the reorder's transform
// writes forces a reflow on every pointer event.
let groupBoxes: Map<'shared' | 'private', DOMRect> | null = null

/** The group list under the given point, deciding both the hover offer and the drop target. */
function groupAt(x: number, y: number): 'shared' | 'private' | null {
  groupBoxes ??= new Map(
    (['shared', 'private'] as const).flatMap((key) => {
      const element = root?.querySelector(`[data-workspace-group-list="${key}"]`)
      return element == null ? [] : [[key, element.getBoundingClientRect()] as const]
    }),
  )

  for (const [key, box] of groupBoxes) {
    if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) {
      return key
    }
  }

  return null
}

watch(
  () => sharedReorder.isMoving || privateReorder.isMoving,
  (moving) => {
    if (!moving) {
      groupBoxes = null
      hoveredGroup = null
    }
  },
)

// Scrolling mid-drag shifts the lists under the cached boxes.
useEventListener(window, 'scroll', () => (groupBoxes = null), { passive: true, capture: true })

useEventListener(window, 'pointermove', (event: PointerEvent) => {
  if (!sharedReorder.isMoving && !privateReorder.isMoving) {
    return
  }

  hoveredGroup = groupAt(event.clientX, event.clientY)
})

/** Take a row released outside its own group, which is either the other group or the tab strip.

Returns whether the drop was claimed, which stops the release from reordering the source group.
*/
function onDrop(workspace: Workspace, from: 'shared' | 'private', event: PointerEvent): boolean {
  // The held row rides under the pointer, so the drop target is the topmost element that is
  // not part of it.
  const held = rowsOf(from).find((row) => row.contains(event.target as Node)) ?? null
  const element =
    document
      .elementsFromPoint(event.clientX, event.clientY)
      .find((candidate) => held == null || !held.contains(candidate)) ?? null
  if (element == null) {
    return false
  }

  if (element.closest('[data-workspace-drop="tabs"]') != null) {
    void openAsTab(workspace).then(() => emit('open', workspace.id))
    return true
  }

  const to = groupAt(event.clientX, event.clientY)
  if (to == null || to === from) {
    return false
  }

  // Publishing a workspace shows it to everyone who can see the placement so that direction is a
  // manager's to make either way. Taking a copy private only ever creates the caller's own
  // workspace so it needs nothing beyond being able to see the original.
  if (to === 'shared' && !canManage) {
    return true
  }

  dialogs.transferWorkspace(workspace, to, canManage).onOk((mode) => {
    void transfer(workspace, to, mode)
  })

  return true
}

async function transfer(workspace: Workspace, to: 'shared' | 'private', mode: 'copy' | 'move') {
  const owner = to === 'private' ? (auth.user?.id ?? null) : null

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
  dialogs.createWorkspace(placement, group === 'private').onOk(async (created) => {
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

// Whether persistOrder's writes are still in flight, which is the only time the hold below may
// outlast an incoming list.
let writing = false

// Each group is positioned within itself so a private workspace never has to be ordered against a
// shared one it is never listed beside.
async function persistOrder(shared: Workspace[], owned: Workspace[]) {
  pending = [...shared, ...owned]
  writing = true

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
            }),
      ),
    )
  } catch {
    notify.error('Failed to save the workspace order.')
    pending = null
  } finally {
    writing = false
  }
}

// The dragged order stands in only while the writes are in flight and the incoming list is the
// same rows differently ordered. Anything else is authoritative and drops the hold.
watch(
  () => inStandardOrder(workspaces),
  (incoming) => {
    if (pending == null) {
      return
    }

    const ids = [
      ...incoming.filter((workspace) => workspace.owner_id == null),
      ...incoming.filter((workspace) => workspace.owner_id != null),
    ].map((workspace) => workspace.id)
    const held = pending.map((workspace) => workspace.id)

    const inFlight =
      writing &&
      ids.length === held.length &&
      [...ids].sort().join('|') === [...held].sort().join('|') &&
      ids.join('|') !== held.join('|')
    if (!inFlight) {
      pending = null
    }
  },
)

function openSettings(workspace: Workspace) {
  dialogs.workspaceSettings(workspace.id).onOk(() => workspaceStore.refresh())
}

function duplicate(workspace: Workspace) {
  dialogs.duplicateWorkspace(workspace.id, workspace.data).onOk((created) => {
    emit('openBeside', workspace.id, created.id)
  })
}

function promptDelete(workspace: Workspace) {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message: `Are you sure you'd like to delete workspace "${workspace.name}"?`,
      note:
        'This action cannot be undone. You and any users with access to this workspace will ' +
        'never see it again. To remove it from your own tabs without deleting it, close the ' +
        'tab instead.',
    })
    .onOk(async () => {
      await workspaceStore.delete(workspace.id)
    })
}

/** A row's menu, one definition serving the dots dropdown and the right-click context menu. */
function menuItems(
  workspace: Workspace,
  groupReorder: ReturnType<typeof usePointerReorder>,
): DropdownMenuItem[][] {
  const opening: DropdownMenuItem[] = [
    { label: 'Open', icon: icons.workspace, onSelect: () => void open(workspace, groupReorder) },
  ]
  if (!isHome) {
    opening.push({
      label: 'Open on Home',
      icon: icons.open,
      onSelect: () => void openOnHome(workspace),
    })
  }

  const editing: DropdownMenuItem[] = []
  if (isWritable(workspace)) {
    editing.push({ label: 'Rename', icon: icons.rename, onSelect: () => openRename(workspace) })
  }
  editing.push(
    { label: 'Settings', icon: icons.settings, onSelect: () => openSettings(workspace) },
    { label: 'Copy Link', icon: icons.share, onSelect: () => emit('share', [workspace.id]) },
    { label: 'Duplicate', icon: icons.duplicate, onSelect: () => duplicate(workspace) },
  )

  const groups = [opening, editing]
  if (isWritable(workspace)) {
    groups.push([{ label: 'Delete', icon: icons.delete, onSelect: () => promptDelete(workspace) }])
  }

  return groups
}
</script>

<template>
  <div ref="root">
    <define-groups>
      <template v-for="group in groups" :key="group.key">
        <!-- A group the caller may add to keeps its heading even while it is empty since that
        heading is where the first one is made from. -->
        <!-- The whole group is a drop target so a workspace can be dragged into one with no
        rows to land on. -->
        <div
          v-if="group.items.length > 0 || group.canAdd"
          :class="[
            $style.group,
            isDropTarget(group.key) && $style.dropZone,
            isDropTarget(group.key) && hoveredGroup === group.key && $style.dropZoneActive,
          ]"
          :data-workspace-group-list="group.key"
        >
          <div class="mb-0.5 flex min-h-5 items-center">
            <c-text variant="description">
              {{ group.items.length === 0 ? `${group.label} (None)` : group.label }}
            </c-text>
            <div class="flex-1" />
            <c-tooltip v-if="group.canAdd" :text="`Create ${group.label} Workspace`">
              <button
                class="mr-4 flex items-center rounded-full opacity-50 transition-opacity hover:opacity-100"
                type="button"
                @click="create(group.key as 'shared' | 'private')"
              >
                <c-icon :name="icons.add" size="16" />
              </button>
            </c-tooltip>
          </div>
          <c-list v-if="group.items.length > 0">
            <c-context-menu
              v-for="(workspace, index) in group.items"
              :key="workspace.id"
              :items="menuItems(workspace, group.reorder)"
            >
              <div
                class="flex cursor-pointer items-center gap-2 py-1 pr-2 hover:bg-elevated"
                :class="[
                  $style.row,
                  group.reorder.isSwapping && $style.swapping,
                  group.reorder.isDragging && $style.arranging,
                  group.reorder.isHeld(index) && $style.held,
                  group.reorder.isGrabbed(index) && $style.grabbed,
                ]"
                :data-workspace-group="group.key"
                :style="group.reorder.styleFor(index)"
                v-bind="group.canReorder ? group.reorder.handlers(index) : {}"
                @click="open(workspace, group.reorder)"
              >
                <!-- A grip appears at the row's leading edge on hover so a draggable row says so
                without spending a column on a handle that is idle the rest of the time. The whole
                row is still the drag target, and the grip is the hint. -->
                <span v-if="group.canReorder" :class="$style.grip">
                  <c-icon :name="icons.dragVertical" size="17" />
                </span>
                <c-icon
                  class="shrink-0"
                  :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
                  size="18"
                />
                <div class="min-w-0 flex-1" @dblclick.stop="openRename(workspace)">
                  <!-- The name alone reports being hovered. Holding shift over a row offers to
                  rename it, and the offer belongs to the text being renamed rather than to the
                  whole row. -->
                  <c-text
                    class="self-start"
                    variant="body2"
                    @mouseenter="setNameHovered(workspace, true)"
                    @mouseleave="setNameHovered(workspace, false)"
                  >
                    <c-inline-name-edit
                      :claim="editingId === workspace.id"
                      :editing="isNaming(workspace)"
                      :name="workspace.name"
                      @rename="(value: string) => rename(workspace, value)"
                      @update:editing="
                        (value: boolean) => (editingId = value ? workspace.id : null)
                      "
                    />
                  </c-text>
                </div>
                <!-- The tab icon both says whether this workspace is on the strip below and puts
                it there or takes it away, filled while it is showing and hollow while it is
                not. -->
                <c-tooltip :delay-duration="500" text="Toggle Tab">
                  <button
                    class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
                    type="button"
                    @click.stop="toggleTab(workspace)"
                    @mousedown.stop
                    @pointerdown.stop
                  >
                    <c-icon :name="isOpen(workspace) ? icons.tab : icons.tabUnselected" size="15" />
                  </button>
                </c-tooltip>
                <c-dropdown-menu :items="menuItems(workspace, group.reorder)">
                  <button
                    class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
                    type="button"
                    @click.stop
                    @mousedown.stop
                    @pointerdown.stop
                  >
                    <c-icon :name="icons.more" size="15" />
                  </button>
                </c-dropdown-menu>
              </div>
            </c-context-menu>
          </c-list>
        </div>
      </template>
    </define-groups>

    <div v-if="collapsible" class="rounded-md border border-default">
      <button
        class="flex w-full items-center gap-1 px-3 py-1.5 text-left"
        type="button"
        @click="expanded = !expanded"
      >
        <c-text variant="body1">Workspaces</c-text>
        <div class="flex-1" />
        <c-icon :name="expanded ? icons.menuUp : icons.menuDown" size="18" />
      </button>
      <div v-if="expanded" class="p-2 pt-0">
        <reuse-groups />
      </div>
    </div>
    <template v-else>
      <c-text class="mb-1 block" variant="body1">Workspaces</c-text>
      <reuse-groups />
    </template>
  </div>
</template>

<style module>
.group + .group {
  margin-top: 10px;
}

.row {
  position: relative;
  padding-left: 22px;
  transition:
    background-color 0.2s,
    transform 0.16s ease;
  touch-action: none;
}

/* The grip's box runs from the row's leading edge to the far side of the workspace icon so that
whole end reads as the place to take hold of. Zero opacity still receives the pointer, carrying
the cursor before the grip fades in. */
.grip {
  position: absolute;
  top: 50%;
  left: 2px;
  z-index: 1;
  display: flex;
  align-items: center;
  width: 38px;
  cursor: grab;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.15s;
}

.row:hover .grip {
  opacity: 0.7;
}

/* While a drag is in progress the list must not clip the lifted row, and hover highlighting on
the rows sliding aside would read as a second thing happening at once. */
.arranging:hover {
  background: inherit;
}

/* Where a held row can be let go, drawn faintly while one travels so the transfer is
discoverable, and filled only while the row is actually over it. Outlined rather than bordered so
offering costs no layout shift. */
.dropZone {
  border-radius: 4px;
  outline: 2px dashed color-mix(in srgb, var(--ui-primary) 30%, transparent);
  outline-offset: 2px;
}

.dropZoneActive {
  outline-color: color-mix(in srgb, var(--ui-primary) 70%, transparent);
  background: color-mix(in srgb, var(--ui-primary) 6%, transparent);
}

/* The lifted row sits above the ones sliding under it so it takes the surface it was lifted off
rather than letting them show through, and thins slightly to read as held. */
.held {
  z-index: 2;
  position: relative;
  opacity: 0.92;
  background: var(--ui-bg);
}

/* The held row tracks the pointer directly so it must not smooth its own movement. The
transition returns on release and animates it into the gap. */
.row.grabbed {
  cursor: grabbing;
  transition: background-color 0.2s;
}

/* Transitions are off across the swap so dropping the transforms while the list reorders does
not replay the slide. */
.row.swapping {
  transition: none;
}
</style>
