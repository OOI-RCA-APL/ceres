<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { QMenu } from 'quasar'
import { nextTick, watch } from 'vue'

import { useAuth } from '@/api/auth'
import WorkspaceChooser from '@/components/WorkspaceChooser.vue'
import WorkspaceTabLabel from '@/components/WorkspaceTabLabel.vue'
import { useDialogs } from '@/dialogs'
import { isWorkspaceFile, useFileDrop } from '@/filedrop'
import icons from '@/icons'
import { useModifiers } from '@/modifiers'
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
  bound = false,
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

  /** Whether this strip belongs to one component, which is what bounds how much opening all is.

  Home draws from every workspace the caller can see, where opening all of them is never what
  anybody meant, so it is only offered on a strip with a placement behind it.
  */
  bound?: boolean
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

// Tabs reorder by pointer rather than by the HTML5 drag API, so they behave the way browser tabs
// do. The same behavior drives the overview's workspace list, which is why it lives in a shared
// composable rather than here.
let rootElement = $ref<HTMLElement | null>(null)

const reorder = usePointerReorder({
  axis: 'horizontal',
  elements: () => [...(rootElement?.querySelectorAll<HTMLElement>('.q-tab') ?? [])],
  onReorder: (from, to) => emit('reorder', moved([...workspaces], from, to)),
  // The strip scrolls once it outgrows its room, so a tab held near either end carries the strip
  // along and can be taken past what is showing.
  scroller: () => rootElement?.querySelector<HTMLElement>('.q-tabs__content') ?? null,
})

// Whether the tabs have outgrown the strip and started scrolling. It decides where the picker
// sits, since a strip with room can keep the button beside its last tab while a scrolling one has
// no such place to put it.
let overflowing = $ref(false)

function measureOverflow() {
  const content = rootElement?.querySelector('.q-tabs__content')
  overflowing = content != null && content.scrollWidth > content.clientWidth + 1
}

useResizeObserver($$(rootElement), measureOverflow)

watch(
  () => workspaces.map((workspace) => workspace.id),
  async () => {
    await nextTick()
    measureOverflow()
  },
  { immediate: true }
)

// The add button offers what is already here before making something new, the way a browser's new
// tab button opens a page of somewhere to go. Holding shift skips the picker, for anyone who knows
// they want a new one.
let picking = $ref(false)

const { shift: shiftHeld } = useModifiers()

// The button says which of the two it is about to do. A chevron for the picker, which is what a
// browser puts at the end of a tab strip to list the rest, and a plus once shift turns it into
// making a new one. The picker opens either way, so that creating is always reached the same way
// rather than the button quietly changing meaning once a strip happens to hold everything.
const opensPicker = $computed(() => !shiftHeld.value)

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

function onTabClick(workspace: Workspace, event: MouseEvent) {
  if (reorder.consumeClick()) {
    return
  }

  // Shift names the tab rather than turning to it, which is what holding shift over one already
  // offers. The press is what makes the offer a real edit, so it outlasts shift being let go of.
  if (event.shiftKey) {
    openRename(workspace)
    return
  }

  emit('select', workspace.id)
}

/** Which tab is showing its name as a field, whether offered or being typed into.

Holding shift over a tab turns its name into a field there and then, so the rename is offered
rather than hidden behind a shortcut nobody would guess. Clicking into it makes it a real edit,
which is what keeps it once shift is let go of.
*/
let hoveredId = $ref<string | null>(null)

// Reported by the label rather than by the tab, so the offer belongs to the text being renamed.
// Leaving only clears what it was set to, since the pointer can reach the next name before the one
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
// with the pointer. Without shift the arrows belong to the strip itself, which steers between
// tabs, so only the shifted pair is taken.
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

  // The tab travels with the key, so focus goes with it rather than staying on whatever has
  // taken its place.
  await nextTick()
  rootElement?.querySelectorAll<HTMLElement>('.q-tab')[to]?.focus()
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

// Which tab is having its name edited in place, if any.
let editingId = $ref<string | null>(null)

// Renaming a workspace changes it for everybody who can see it, so it takes the same write access
// deleting does rather than being offered to anyone who can merely look at it.
function openRename(workspace: Workspace) {
  if (!isWritable(workspace)) {
    return
  }

  editingId = workspace.id
}

// The active tab renames through the live workspace context, so the same handler that persists the
// standalone header's rename keeps doing so here. Any other tab has no context loaded, so it goes
// to the store directly.
async function rename(workspace: Workspace, value: string) {
  if (workspace.id === active && activeActions != null) {
    await activeActions.rename(value)
    return
  }

  await workspaceStore.rename(workspace.id, value)
}

function openSettingsById(workspace: Workspace) {
  dialogs.workspaceSettings(workspace.id).onOk(() => workspaceStore.refresh())
}

function duplicateById(workspace: Workspace) {
  dialogs.duplicateWorkspace(workspace.id, workspace.data).onOk((created: Workspace) => {
    emit('openBeside', workspace.id, created.id)
  })
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
        @click="onTabClick(workspace, $event)"
        @dblclick.stop="openRename(workspace)"
        @keydown="onTabKeydown($event, index)"
      >
        <div
          :class="[$style.tabInner, 'items-center', 'no-wrap', 'row']"
          @dblclick.stop="openRename(workspace)"
        >
          <!-- The tab's leading edge carries the grab cursor, which is all a tab needs to say it
          can be dragged, since a strip of tabs already reads as one. The whole tab is the drag
          target, so this is a hint rather than a handle. -->
          <span :class="$style.grip" />
          <workspace-tab-label
            :claim="editingId === workspace.id"
            :editing="isNaming(workspace)"
            :show-placement="showPlacement"
            :workspace="workspace"
            @hover-name="(value: boolean) => setNameHovered(workspace, value)"
            @rename="(value: string) => rename(workspace, value)"
            @update:editing="(value: boolean) => (editingId = value ? workspace.id : null)"
          />
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
                  <q-item
                    v-close-popup
                    clickable
                    dense
                    :disable="workspaces.length < 2"
                    @click="emit('closeOthers', workspace.id)"
                  >
                    <q-item-section avatar>
                      <q-icon :name="icons.closeOthers" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close Other Tabs</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable dense @click="emit('closeAll')">
                    <q-item-section avatar>
                      <q-icon :name="icons.closeAll" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close All</q-item-label>
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
                  <q-item v-close-popup clickable dense @click="activeActions.openSettings()">
                    <q-item-section avatar>
                      <q-icon :name="icons.settings" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Settings</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-separator />
                  <q-item v-close-popup clickable dense @click="emit('share', [active!])">
                    <q-item-section avatar>
                      <q-icon :name="icons.share" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Copy Link</q-item-label>
                    </q-item-section>
                  </q-item>
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
                  <q-item
                    v-close-popup
                    clickable
                    dense
                    :disable="workspaces.length < 2"
                    @click="emit('closeOthers', workspace.id)"
                  >
                    <q-item-section avatar>
                      <q-icon :name="icons.closeOthers" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close Other Tabs</q-item-label>
                    </q-item-section>
                  </q-item>
                  <q-item v-close-popup clickable dense @click="emit('closeAll')">
                    <q-item-section avatar>
                      <q-icon :name="icons.closeAll" />
                    </q-item-section>
                    <q-item-section>
                      <q-item-label>Close All</q-item-label>
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
                  <q-item v-close-popup clickable dense @click="openSettingsById(workspace)">
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
            <q-tooltip class="bg-primary text-white" :delay="500">Close Workspace</q-tooltip>
          </q-btn>
        </div>
      </q-tab>
    </q-tabs>
    <!-- The picker sits beside the last tab while there is room for it there, takes the middle of
    an empty strip rather than hugging an edge with nothing next to it, and pins to the trailing
    edge once the tabs have outgrown the strip and begun to scroll under it. -->
    <q-btn
      v-if="canCreate"
      :class="[
        $style.add,
        workspaces.length === 0 && $style.addCentered,
        workspaces.length > 0 && overflowing && $style.addAnchored,
        'q-ml-xs',
      ]"
      dense
      flat
      :icon="opensPicker ? icons.chevronDown : icons.add"
      round
      size="sm"
      @click="onAddClick"
    >
      <!-- The chevron speaks for itself, so only the plus that shift turns it into is named. -->
      <q-tooltip v-if="!opensPicker" class="bg-primary text-white">Create Workspace</q-tooltip>
      <!-- Opened from the click handler alone, so holding shift can bypass it. Left to its own
      devices a menu inside a button opens on every click, shift or not. -->
      <q-menu
        v-model="picking"
        anchor="bottom middle"
        no-parent-event
        :offset="[0, 4]"
        self="top middle"
      >
        <q-card bordered :class="$style.picker" flat>
          <workspace-chooser
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
          <!-- Both stay on the menu whatever the strip holds, so each is where it was last time
          rather than appearing and vanishing as the strip fills and empties, and each is simply
          spent once there is nothing left for it to do. Opening all is offered only on a strip
          with a placement behind it, where what it opens is bounded by what is on this component.
          Closing has no such bound to worry about. -->
          <q-separator />
          <q-list dense>
            <q-item
              v-if="bound"
              v-close-popup
              clickable
              dense
              :disable="openable.length === 0"
              @click="emit('openAll')"
            >
              <q-item-section avatar>
                <q-icon :name="icons.tabAdd" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  Open All<template v-if="openable.length > 0"> ({{ openable.length }})</template>
                </q-item-label>
              </q-item-section>
            </q-item>
            <q-item
              v-close-popup
              clickable
              dense
              :disable="workspaces.length === 0"
              @click="emit('closeAll')"
            >
              <q-item-section avatar>
                <q-icon :name="icons.closeAll" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  Close All<template v-if="workspaces.length > 0">
                    ({{ workspaces.length }})</template
                  >
                </q-item-label>
              </q-item-section>
            </q-item>
            <!-- The whole strip rather than one tab, so a link hands over the set of workspaces
            being looked at together and opens all of them where it lands. -->
            <q-item
              v-close-popup
              clickable
              dense
              :disable="workspaces.length === 0"
              @click="
                emit(
                  'share',
                  workspaces.map((workspace) => workspace.id)
                )
              "
            >
              <q-item-section avatar>
                <q-icon :name="icons.share" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  Copy Link{{ workspaces.length === 1 ? '' : 's' }}
                  <template v-if="workspaces.length > 0">({{ workspaces.length }})</template>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </q-menu>
    </q-btn>
  </div>
</template>

<style lang="scss" module>
@use '@/css/tab-strip' as strip;

// The strip takes the full height of the header row it sits in and its tabs stretch to fill it, so
// the selected tab's fill runs from the top of the header into the separator beneath it, the way a
// tab is expected to meet the surface it belongs to. The picker floats over the trailing edge
// rather than reserving space beside the tabs, so it stays in the same place however long the strip
// grows and the tabs pass beneath it.
.root {
  position: relative;
  flex: 1;
  align-self: stretch;
  align-items: stretch;
  min-width: 0;
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
  @include strip.scroller;
}

// Stretched to the header's full height on top of what the strip clears, so the selected tab's
// fill reaches the separator under the header.
.tabs .tab {
  @include strip.tabUnpadded;

  height: 100%;
}

.tab :global(.q-tab__content) {
  @include strip.tabContentUnpadded;
}

// Each tab carries the workspace icon so the group reads as workspaces rather than as page
// sections, and the selected one is marked by a filled block instead of an underline, which sits
// better in a header rail that already uses chips and icon buttons.
.tab {
  @include strip.tab;
}

// The grip and the close button sit against the tab's own edges rather than inside the row, so they
// cost the same width whether they are showing or not and the label never moves.
.tabInner {
  height: 100%;
  padding: 0 20px 0 19px;
}

// Reaching past the workspace icon, so the whole leading edge of the tab says it can be dragged.
.grip {
  @include strip.grip(32px);
}

.tabIcon {
  font-size: 15px;
  margin-right: 5px;
}

.label {
  @include strip.label;

  font-size: 13px;
}

// The extra pixel matches the nudge on the menu button beside it, so the two sit on one line.
.close {
  @include strip.close(1px);
}

// The selected tab keeps its close button visible, since that is the one most likely to be closed
// next.
.tab:hover .close,
.closeShown {
  opacity: 1;
}

// A workspace with local changes rings its menu dots rather than carrying an icon of its own. The
// ring is drawn on the dots themselves so it sits tight against them and leaves the button's hit
// area alone, and being an outline it takes no space, keeping a tab exactly as wide edited as it is
// clean. Quasar buttons carry `no-outline`, which clears outlines with `!important`, so this has to
// be forced back on.
.editedRing :global(.q-icon) {
  border-radius: 50%;
  outline: 1px dotted currentColor !important;
  outline-offset: 0;
}

.arranging {
  @include strip.arranging;
}

.held {
  @include strip.held;
}

.grabbed {
  @include strip.grabbed;
}

.swapping {
  @include strip.swapping;
}

// Wide enough for a workspace name and its placement without the menu sizing itself to whatever
// happens to be listed.
.picker {
  min-width: 280px;
}

.add {
  @include strip.add;
  @include strip.fadedIcon;
}

.addCentered {
  @include strip.addCentered;
}

// Flush against the trailing edge with that side squared off, so no sliver of a tab shows past it
// and the strip ends on the button rather than beside it.
.addAnchored {
  @include strip.addAnchored(0);
}

:global(.dark) .addAnchored,
:global(.dark) .addCentered {
  background-color: $dark;
}

:global(.light) .addAnchored,
:global(.light) .addCentered {
  background-color: white;
}
</style>
