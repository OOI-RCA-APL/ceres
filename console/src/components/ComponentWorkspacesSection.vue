<script lang="ts" setup>
import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { moved, usePointerReorder } from '@/reorder'
import { useTabs } from '@/tabs'
import { inStandardOrder, isWorkspaceWritable, useWorkspaces, Workspace } from '@/workspace'

const { workspaces, placement, canManage } = defineProps<{
  /** Every workspace placed here that the caller can view, whether or not it is open. */
  workspaces: Workspace[]
  placement: string
  /** Whether the caller may manage the placement, which is what the shared order follows. */
  canManage: boolean
}>()

const emit = defineEmits<{ open: [id: string] }>()

const auth = useAuth()
const dialogs = useDialogs()
const tabs = useTabs()
const workspaceStore = useWorkspaces()

const ordered = $computed(() => pending ?? inStandardOrder(workspaces))

// A workspace is in the strip unless the user has closed it. An untouched strip is its defaults,
// so absence from `open` is not the same as being closed.
function isOpen(workspace: Workspace): boolean {
  const set = tabs.setFor(placement)
  if (set.open.includes(workspace.id)) {
    return true
  }

  return !set.closed.includes(workspace.id)
}

function isWritable(workspace: Workspace): boolean {
  return isWorkspaceWritable(workspace, auth.user?.id, canManage)
}

async function open(workspace: Workspace, groupReorder: ReturnType<typeof usePointerReorder>) {
  // Releasing a drag must not also open what was dragged.
  if (groupReorder.consumeClick()) {
    return
  }

  await tabs.open(placement, workspace.id)
  emit('open', workspace.id)
}

// A workspace opened on home keeps its placement, so its widgets still resolve relative addresses
// against this component wherever it is being viewed from.
async function openOnHome(workspace: Workspace) {
  await tabs.open(engineRoot, workspace.id)
}

// Shared and private are listed apart rather than mixed, because they answer different questions.
// The shared ones are what this component offers everyone who can see it, and the private ones are
// the caller's own work on it, which nobody else has.
const sharedWorkspaces = $computed(() => ordered.filter((workspace) => workspace.owner_id == null))
const privateWorkspaces = $computed(() => ordered.filter((workspace) => workspace.owner_id != null))

// The standard order is what a user sees before they have arranged this strip themselves, so it is
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
})

const privateReorder = usePointerReorder({
  axis: 'vertical',
  elements: () => rowsOf('private'),
  onReorder: (from, to) =>
    void persistOrder(sharedWorkspaces as Workspace[], moved(privateWorkspaces, from, to)),
})

const groups = $computed(() => [
  {
    key: 'shared',
    label: 'Shared',
    items: sharedWorkspaces,
    reorder: sharedReorder,
    canReorder: canManage,
  },
  {
    key: 'private',
    label: 'Private',
    items: privateWorkspaces,
    reorder: privateReorder,
    canReorder: true,
  },
])

// Each group is positioned within itself, so a private workspace never has to be ordered against a
// shared one it is never listed beside.
async function persistOrder(shared: Workspace[], owned: Workspace[]) {
  pending = [...shared, ...owned]

  // Every position is rewritten rather than just the pair that moved, because a workspace that has
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
  dialogs.duplicateWorkspace(workspace.id, workspace.data)
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
    <div class="items-center q-mb-xs row text-subtitle2">
      Workspaces
      <q-chip class="q-ml-xs" dense :label="ordered.length" outline size="sm" />
    </div>
    <div v-if="ordered.length === 0" class="text-grey-6" :class="$style.empty">No workspaces.</div>
    <template v-for="group in groups" :key="group.key">
      <div v-if="group.items.length > 0" :class="$style.group">
        <div class="text-grey-6" :class="$style.groupLabel">{{ group.label }}</div>
        <q-list bordered class="rounded-borders" dense separator>
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
            <q-item-section avatar>
              <q-icon
                :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
                size="18px"
              />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ workspace.name }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="isOpen(workspace)" side>
              <q-chip dense :label="'Open'" outline size="sm" />
            </q-item-section>
            <q-item-section side>
              <q-btn dense flat :icon="icons.more" round size="8px" @click.stop>
                <q-menu anchor="bottom right" :offset="[0, 4]" self="top right">
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
                      <q-item v-close-popup clickable dense @click="openOnHome(workspace)">
                        <q-item-section avatar>
                          <q-icon :name="icons.open" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Open on Home</q-item-label>
                        </q-item-section>
                      </q-item>
                      <q-separator />
                      <q-item v-close-popup clickable dense @click="openSettings(workspace)">
                        <q-item-section avatar>
                          <q-icon :name="icons.settings" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>Settings</q-item-label>
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
              </q-btn>
            </q-item-section>
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

.groupLabel {
  margin-bottom: 2px;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.row {
  transition: background-color 0.2s, transform 0.16s ease;
  touch-action: none;
}

// While a drag is in progress the list must not clip the lifted row, and hover highlighting on the
// rows sliding aside would read as a second thing happening at once.
.arranging:hover {
  background: inherit;
}

.held {
  z-index: 2;
  position: relative;
  background: var(--q-dark-page, transparent);
}

// The held row tracks the pointer directly, so it must not smooth its own movement. It regains the
// transition once released, which is what animates it into the gap.
.grabbed {
  cursor: grabbing;
  transition: background-color 0.2s;
}

.swapping {
  transition: none;
}
</style>
