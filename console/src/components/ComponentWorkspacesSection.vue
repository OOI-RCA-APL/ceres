<script lang="ts" setup>
import { engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
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

const ordered = $computed(() => inStandardOrder(workspaces))

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

async function open(workspace: Workspace) {
  await tabs.open(placement, workspace.id)
  emit('open', workspace.id)
}

// A workspace opened on home keeps its placement, so its widgets still resolve relative addresses
// against this component wherever it is being viewed from.
async function openOnHome(workspace: Workspace) {
  await tabs.open(engineRoot, workspace.id)
}

// The standard order is what a user sees before they have arranged this strip themselves, so it is
// shared and only a manager may change it. Dragging a tab arranges one person's own strip, which
// is why moving a workspace in the shared order happens here instead.
async function move(workspace: Workspace, offset: number) {
  const current = ordered.findIndex((candidate) => candidate.id === workspace.id)
  const target = current + offset
  if (current < 0 || target < 0 || target >= ordered.length) {
    return
  }

  const moved = [...ordered]
  moved.splice(target, 0, ...moved.splice(current, 1))

  // Every position is rewritten rather than just the pair, because a workspace that has never been
  // positioned has no order at all and would otherwise keep sorting last.
  await Promise.all(
    moved.map((candidate, index) =>
      candidate.data.meta.order === index
        ? Promise.resolve()
        : workspaceStore.update(candidate.id, {
            data: { ...candidate.data, meta: { ...candidate.data.meta, order: index } },
          })
    )
  )
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
  <q-expansion-item dense dense-toggle :label="`Workspaces (${ordered.length})`">
    <q-list class="q-pb-sm" dense>
      <q-item v-if="ordered.length === 0">
        <q-item-section>
          <q-item-label class="text-grey-6">No workspaces.</q-item-label>
        </q-item-section>
      </q-item>
      <q-item v-for="workspace in ordered" :key="workspace.id" clickable @click="open(workspace)">
        <q-item-section avatar>
          <q-icon
            :name="workspace.owner_id != null ? icons.privateWorkspace : icons.workspace"
            size="18px"
          >
            <q-tooltip v-if="workspace.owner_id != null" :delay="1000">
              This workspace is private to you.
            </q-tooltip>
          </q-icon>
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ workspace.name }}</q-item-label>
        </q-item-section>
        <q-item-section v-if="isOpen(workspace)" side>
          <q-chip dense :label="'Open'" outline size="sm" />
        </q-item-section>
        <q-item-section side>
          <q-btn dense flat :icon="icons.more" round size="sm" @click.stop>
            <q-menu anchor="bottom right" :offset="[0, 4]" self="top right">
              <q-card bordered flat>
                <q-list dense>
                  <q-item v-close-popup clickable dense @click="open(workspace)">
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
                  <template v-if="canManage">
                    <q-separator />
                    <q-item
                      clickable
                      dense
                      :disable="workspace.id === ordered[0]?.id"
                      @click="move(workspace, -1)"
                    >
                      <q-item-section avatar>
                        <q-icon :name="icons.menuUp" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Move Up</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item
                      clickable
                      dense
                      :disable="workspace.id === ordered[ordered.length - 1]?.id"
                      @click="move(workspace, 1)"
                    >
                      <q-item-section avatar>
                        <q-icon :name="icons.menuDown" />
                      </q-item-section>
                      <q-item-section>
                        <q-item-label>Move Down</q-item-label>
                      </q-item-section>
                    </q-item>
                  </template>
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
  </q-expansion-item>
</template>
