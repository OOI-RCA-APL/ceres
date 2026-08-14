<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { useResizeObserver } from '@vueuse/core'
import { nextTick, watch } from 'vue'

import { useAuth } from '@/api/auth'
import { useDialogs } from '@/dialogs'
import { isWorkspaceFile, useFileDrop } from '@/filedrop'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
import { moved, usePointerReorder } from '@/reorder'
import { isStructurallyEqual } from '@/utilities'
import {
  comparableWorkspaceData,
  isWorkspaceWritable,
  useWorkspaces,
  type Workspace,
  type WorkspaceEdit,
  type WorkspaceHeaderActions,
  type WorkspaceHeaderState,
} from '@/workspace'

const {
  workspaces,
  active,
  canManage,
  canCreate,
  openable = [],
  showPlacement = false,
  bound = false,
  trailingInset = 0,
  docked = false,
  activeActions,
  activeState,
} = defineProps<{
  workspaces: Workspace[]
  active: string | null
  /** Workspaces placed here that the strip is not currently showing, offered by the add button. */
  openable?: Workspace[]
  /** Whether this strip mixes placements, which makes naming them on each tab useful. */
  showPlacement?: boolean
  /** Whether the caller may manage the component, which a shared workspace here follows. */
  canManage: boolean
  /** Whether the caller may add a workspace here, which needs only view since it lands private. */
  canCreate: boolean

  /** Whether this strip belongs to one component.

  "Open all" is only offered on a bound strip since home draws from every workspace the caller
  can see and opening all of those is never intended.
  */
  bound?: boolean

  /** Room in pixels the host's own trailing controls take at the strip's right edge, which
  the anchored picker stays clear of. */
  trailingInset?: number

  /** Whether the strip is resting at the bottom edge of the screen, where the picker's menu
  opens upward and its chevron says so. */
  docked?: boolean

  activeActions?: WorkspaceHeaderActions
  activeState?: WorkspaceHeaderState
}>()

const emit = defineEmits<{
  select: [id: string]
  close: [id: string]
  closeOthers: [id: string]
  closeAll: []
  open: [id: string]
  openAll: []
  /** A copy to put on the strip directly after the workspace it was copied from. */
  openBeside: [afterId: string, id: string]
  /** Workspaces to copy a link to, which the page builds from its own placement. */
  share: [ids: string[]]
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

// Tabs reorder by pointer rather than by the HTML5 drag API so they behave the way browser tabs
// do. The same behavior drives the overview's workspace list, which is why it lives in a shared
// composable rather than here.
let rootElement = $ref<HTMLElement | null>(null)
let scrollerElement = $ref<HTMLElement | null>(null)

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(scrollerElement?.querySelectorAll<HTMLElement>('[data-tab]') ?? [])],
  onReorder: (from, to) => emit('reorder', moved([...workspaces], from, to)),
  // The strip scrolls once it outgrows its room so a tab held near either end carries the strip
  // along and can be taken past what is showing.
  scroller: () => scrollerElement,
})

// Whether the tabs have outgrown the strip and started scrolling. It decides where the picker
// sits since a strip with room can keep the button beside its last tab while a scrolling one has
// no such place to put it.
let overflowing = $ref(false)

function measureOverflow() {
  overflowing =
    scrollerElement != null && scrollerElement.scrollWidth > scrollerElement.clientWidth + 1
}

useResizeObserver($$(rootElement), measureOverflow)

watch(
  () => workspaces.map((workspace) => workspace.id),
  async () => {
    await nextTick()
    measureOverflow()
  },
  { immediate: true },
)

// The add button offers what is already here before making something new, the way a browser's new
// tab button opens a page of somewhere to go. Holding shift skips the picker, for anyone who knows
// they want a new one.
let picking = $ref(false)

const { shift: shiftHeld } = useModifiers()

// The button's icon says which of the two it is about to do, a chevron for the picker and a plus
// once shift turns it into creating. The picker opens either way so creating is always reached
// the same way.
const opensPicker = $computed(() => !shiftHeld.value)

// Intercepted ahead of the popover's own trigger so shift can bypass the picker entirely.
function onAddClick(event: MouseEvent) {
  if (event.shiftKey) {
    event.stopPropagation()
    picking = false
    emit('create')
  }
}

function onTabClick(workspace: Workspace, event: MouseEvent) {
  if (reorder.consumeClick()) {
    return
  }

  // Shift renames the tab rather than turning to it. The press makes the rename a real edit, so
  // it outlasts shift being released.
  if (event.shiftKey) {
    openRename(workspace)
    return
  }

  emit('select', workspace.id)
}

/** Which tab is showing its name as a field, whether offered or being typed into.

Holding shift over a tab turns its name into a field in place so renaming is discoverable.
Clicking into it makes it a real edit that survives shift being released.
*/
let hoveredId = $ref<string | null>(null)

// Reported by the label rather than by the tab so the offer belongs to the text being renamed.
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

// Shift with an arrow key arranges the strip from the keyboard, the same as dragging a tab does
// with the pointer.
async function onTabKeydown(event: KeyboardEvent, index: number) {
  if (!event.shiftKey) {
    return
  }

  const step = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  const to = index + step
  if (step === 0 || to < 0 || to >= workspaces.length) {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  emit('reorder', moved([...workspaces], index, to))

  // The tab travels with the key so focus goes with it rather than staying on whatever has
  // taken its place.
  await nextTick()
  scrollerElement?.querySelectorAll<HTMLElement>('[data-tab]')[to]?.focus()
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
  { immediate: true },
)

// Computed as one map so the deep compares re-run when the edits or workspaces change, not on
// every hover or drag re-render of the strip.
const workingCopyIds = $computed(() => {
  const ids = new Set<string>()
  for (const workspace of workspaces) {
    const edit = edits[workspace.id]
    if (
      edit != null &&
      !isStructurallyEqual(
        comparableWorkspaceData(edit.data),
        comparableWorkspaceData(workspace.data),
      )
    ) {
      ids.add(workspace.id)
    }
  }

  return ids
})

function hasWorkingCopy(workspace: Workspace): boolean {
  if (workspace.id === active && activeState != null) {
    return activeState.edited
  }

  return workingCopyIds.has(workspace.id)
}

// Which tab is having its name edited in place, if any.
let editingId = $ref<string | null>(null)

// Renaming a workspace changes it for everybody who can see it so it takes the same write access
// deleting does rather than being offered to anyone who can merely look at it.
function openRename(workspace: Workspace) {
  if (!isWritable(workspace)) {
    return
  }

  editingId = workspace.id
}

// The active tab renames through the live workspace context so the same handler that persists the
// standalone header's rename keeps doing so here. Any other tab has no context loaded so it goes
// to the store directly.
async function rename(workspace: Workspace, value: string) {
  if (workspace.id === active && activeActions != null) {
    activeActions.rename(value)
    return
  }

  await workspaceStore.rename(workspace.id, value)
}

function openSettingsById(workspace: Workspace) {
  dialogs.workspaceSettings(workspace.id).onOk(() => workspaceStore.refresh())
}

function duplicateById(workspace: Workspace) {
  dialogs.duplicateWorkspace(workspace.id, workspace.data).onOk((created) => {
    emit('openBeside', workspace.id, created.id)
  })
}

function promptDeleteById(workspace: Workspace) {
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

type MenuItem = DropdownMenuItem

/** The tab's menu, one definition serving the dots dropdown and the right-click context menu. */
function menuItems(workspace: Workspace): MenuItem[][] {
  const isActive = workspace.id === active && activeActions != null && activeState != null
  const closing: MenuItem[] = [
    { label: 'Close', icon: icons.close, onSelect: () => emit('close', workspace.id) },
    {
      label: 'Close Other Tabs',
      icon: icons.closeOthers,
      disabled: workspaces.length < 2,
      onSelect: () => emit('closeOthers', workspace.id),
    },
    { label: 'Close All', icon: icons.closeAll, onSelect: () => emit('closeAll') },
  ]

  const editing: MenuItem[] = []
  if (isWritable(workspace)) {
    editing.push({ label: 'Rename', icon: icons.rename, onSelect: () => openRename(workspace) })
  }
  editing.push({
    label: 'Settings',
    icon: icons.settings,
    onSelect: () =>
      isActive && activeActions != null
        ? activeActions.openSettings()
        : openSettingsById(workspace),
  })

  const sharing: MenuItem[] = [
    { label: 'Copy Link', icon: icons.share, onSelect: () => emit('share', [workspace.id]) },
    {
      label: 'Duplicate',
      icon: icons.duplicate,
      onSelect: () =>
        isActive && activeActions != null ? activeActions.duplicate() : duplicateById(workspace),
    },
  ]
  if (isActive && activeActions != null) {
    sharing.push({
      label: 'Export',
      icon: icons.export,
      onSelect: () => activeActions.exportFile(),
    })
  }

  const groups = [closing, editing, sharing]

  const mayDelete = isActive ? activeState?.canManage === true : isWritable(workspace)
  if (mayDelete) {
    groups.push([
      {
        label: 'Delete',
        icon: icons.delete,
        onSelect: () =>
          isActive && activeActions != null
            ? activeActions.promptDelete()
            : promptDeleteById(workspace),
      },
    ])
  }

  if (isActive && activeState?.edited === true && activeState.isViewingOriginal) {
    groups.push([
      {
        label: 'Revert to Original Version',
        icon: icons.revertToOriginal,
        color: 'warning',
        onSelect: () => activeActions?.promptRevert(),
      },
      {
        label: 'Stop Viewing Original',
        icon: icons.close,
        onSelect: () => activeActions?.stopViewingOriginal(),
      },
    ])
  }

  return groups
}
</script>

<!-- The strip takes the full height of the header row it sits in and its tabs stretch to fill it,
so the selected tab's fill runs from the top of the header into the separator beneath it, the way
a tab is expected to meet the surface it belongs to. The picker floats over the trailing edge
rather than reserving space beside the tabs so it stays in the same place however long the strip
grows and the tabs pass beneath it. -->
<template>
  <div
    ref="rootElement"
    class="relative flex min-w-0 flex-1 flex-nowrap items-stretch self-stretch overflow-hidden pt-1"
    :class="fileDrop.active.value && $style.dropTarget"
    data-workspace-drop="tabs"
    v-bind="canCreate ? fileDrop.handlers : {}"
  >
    <div
      ref="scrollerElement"
      class="flex min-w-0 flex-nowrap items-stretch pl-2"
      :class="$style.scroller"
    >
      <c-context-menu
        v-for="(workspace, index) in workspaces"
        :key="workspace.id"
        :items="menuItems(workspace)"
      >
        <div
          :aria-selected="workspace.id === active"
          :class="[
            $style.tab,
            workspace.id === active && $style.activeTab,
            reorder.isSwapping && $style.swapping,
            reorder.isDragging && $style.arranging,
            reorder.isHeld(index) && $style.held,
            reorder.isGrabbed(index) && $style.grabbed,
          ]"
          data-tab
          role="tab"
          :style="reorder.styleFor(index)"
          tabindex="0"
          v-bind="reorder.handlers(index)"
          @click="onTabClick(workspace, $event)"
          @dblclick.stop="openRename(workspace)"
          @keydown="onTabKeydown($event, index)"
        >
          <div class="relative flex h-full flex-nowrap items-center pl-[19px] pr-5">
            <!-- The tab's leading edge carries the grab cursor, which is all a tab needs to say it
            can be dragged since a strip of tabs already reads as one. The whole tab is the drag
            target so this is a hint rather than a handle. -->
            <span :class="$style.grip" />
            <c-workspace-tab-label
              :claim="editingId === workspace.id"
              :editing="isNaming(workspace)"
              :show-placement="showPlacement"
              :workspace="workspace"
              @hover-name="(value: boolean) => setNameHovered(workspace, value)"
              @rename="(value: string) => rename(workspace, value)"
              @update:editing="(value: boolean) => (editingId = value ? workspace.id : null)"
            />
            <c-dropdown-menu :items="menuItems(workspace)">
              <c-tooltip
                :disabled="!hasWorkingCopy(workspace)"
                text="This workspace has unsaved changes."
              >
                <button
                  class="ml-1 flex items-center rounded-full opacity-60 hover:opacity-100"
                  type="button"
                  @click.stop
                  @mousedown.stop
                  @pointerdown.stop
                  @touchstart.stop
                >
                  <c-icon
                    :class="hasWorkingCopy(workspace) && $style.editedRing"
                    :name="icons.more"
                    size="13"
                  />
                </button>
              </c-tooltip>
            </c-dropdown-menu>
            <c-tooltip :delay-duration="500" text="Close Workspace">
              <button
                :class="[$style.close, workspace.id === active && $style.closeShown]"
                type="button"
                @click.stop="emit('close', workspace.id)"
                @mousedown.stop
                @pointerdown.stop
                @touchstart.stop
              >
                <c-icon :name="icons.close" size="13" />
              </button>
            </c-tooltip>
          </div>
        </div>
      </c-context-menu>
    </div>
    <!-- The picker sits beside the last tab while there is room for it there, takes the middle of
    an empty strip rather than hugging an edge with nothing next to it, and pins to the trailing
    edge, beside any overlaid host controls, once the tabs have outgrown the strip and begun to
    scroll under it. -->
    <c-popover
      v-if="canCreate"
      v-model:open="picking"
      :content="{ side: docked ? 'top' : 'bottom', align: 'center', sideOffset: 4 }"
    >
      <c-tooltip :disabled="opensPicker" text="Create Workspace">
        <button
          class="z-[2] flex w-[34px] flex-none items-center justify-center bg-default text-muted hover:text-default"
          :class="[
            workspaces.length === 0 && 'mx-auto',
            workspaces.length > 0 && overflowing ? 'absolute inset-y-0' : 'ml-1 self-stretch',
          ]"
          :style="
            trailingInset > 0
              ? workspaces.length > 0 && overflowing
                ? { right: `${trailingInset}px` }
                : { marginRight: `${trailingInset}px` }
              : undefined
          "
          type="button"
          @click.capture="onAddClick"
        >
          <!-- The chevron speaks for itself so only the plus that shift turns it into is named. -->
          <c-icon
            :name="opensPicker ? (docked ? icons.chevronUp : icons.chevronDown) : icons.add"
            size="18"
          />
        </button>
      </c-tooltip>
      <template #content>
        <div class="min-w-[280px]">
          <c-workspace-chooser
            create-label="Create Workspace"
            empty="All of them are already open."
            :items="openable"
            @create="
              () => {
                picking = false
                emit('create')
              }
            "
            @select="
              (workspace: Workspace) => {
                picking = false
                emit('open', workspace.id)
              }
            "
          />
          <!-- Both stay on the menu whatever the strip holds so each is where it was last time
          rather than appearing and vanishing as the strip fills and empties, and each is simply
          spent once there is nothing left for it to do. Opening all is offered only on a strip
          with a placement behind it, where what it opens is bounded by what is on this component.
          Closing has no such bound to worry about. -->
          <c-separator />
          <div class="py-1">
            <button
              v-if="bound"
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated disabled:opacity-50"
              :disabled="openable.length === 0"
              type="button"
              @click="((picking = false), emit('openAll'))"
            >
              <c-icon :name="icons.tabAdd" size="18" />
              <c-text variant="body2">
                Open All<template v-if="openable.length > 0"> ({{ openable.length }})</template>
              </c-text>
            </button>
            <button
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated disabled:opacity-50"
              :disabled="workspaces.length === 0"
              type="button"
              @click="((picking = false), emit('closeAll'))"
            >
              <c-icon :name="icons.closeAll" size="18" />
              <c-text variant="body2">
                Close All<template v-if="workspaces.length > 0">
                  ({{ workspaces.length }})</template
                >
              </c-text>
            </button>
            <!-- The whole strip rather than one tab so a link hands over the set of workspaces
            being looked at together and opens all of them where it lands. -->
            <button
              class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-elevated disabled:opacity-50"
              :disabled="workspaces.length === 0"
              type="button"
              @click="
                ((picking = false),
                emit(
                  'share',
                  workspaces.map((workspace) => workspace.id),
                ))
              "
            >
              <c-icon :name="icons.share" size="18" />
              <c-text variant="body2">
                Copy Link{{ workspaces.length === 1 ? '' : 's' }}
                <template v-if="workspaces.length > 0">({{ workspaces.length }})</template>
              </c-text>
            </button>
          </div>
        </div>
      </template>
    </c-popover>
  </div>
</template>

<style module>
/* The scroller hides its bar, the way a browser's tab bar does, and a tab held near either end
carries the strip along instead. */
.scroller {
  overflow-x: auto;
  scrollbar-width: none;
}

.scroller::-webkit-scrollbar {
  display: none;
}

/* An inset outline rather than a border so the strip does not shift by a pixel when a file is
dragged over it. */
.dropTarget {
  box-shadow: inset 0 0 0 2px var(--ui-primary);
  border-radius: 4px;
}

.tab {
  position: relative;
  height: 100%;
  border-radius: 4px 4px 0 0;
  opacity: 0.7;
  transition:
    background-color 0.2s,
    opacity 0.2s,
    transform 0.16s ease;
  touch-action: none;
  cursor: pointer;
  user-select: none;
}

.tab:hover {
  opacity: 1;
}

.activeTab {
  opacity: 1;
  background-color: var(--ui-primary);
  color: #fff;
}

/* Reaching past the workspace icon so the whole leading edge of the tab says it can be dragged. */
.grip {
  position: absolute;
  z-index: 1;
  top: 0;
  bottom: 0;
  left: 0;
  width: 32px;
  cursor: grab;
}

/* The close button holds its place whether or not it is showing, so a tab is exactly as wide
hovered as it is at rest and the strip does not shuffle under the pointer. */
.close {
  position: absolute;
  top: 50%;
  right: 4px;
  display: flex;
  align-items: center;
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.15s;
}

/* The selected tab keeps its close button visible since that is the one most likely to be closed
next. */
.tab:hover .close,
.closeShown {
  opacity: 1;
}

/* A workspace with local changes rings its menu dots rather than carrying an icon of its own. The
ring is drawn on the dots themselves so it sits tight against them and leaves the button's hit
area alone, and being an outline it takes no space, keeping a tab exactly as wide edited as it is
clean. */
.editedRing {
  border-radius: 50%;
  outline: 1px dotted currentColor;
  outline-offset: 0;
}

/* While a drag is in progress the strip must not clip the lifted tab, and hover highlighting on
the tabs sliding aside would read as a second thing happening at once. */
.arranging:hover {
  opacity: inherit;
}

/* The tab that has been picked up, which is drawn over the ones it is passing. */
.held {
  z-index: 2;
  opacity: 1;
}

/* The held tab tracks the pointer directly so it must not smooth its own movement. It regains
the transition once released, which animates it into the gap. */
.grabbed {
  cursor: grabbing;
  transition:
    background-color 0.2s,
    opacity 0.2s;
}

/* The tabs sliding aside move at once rather than each animating from wherever it was. */
.swapping {
  transition: none;
}
</style>
