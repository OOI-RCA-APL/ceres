<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import ComponentWorkspaceTabs from '@/components/ComponentWorkspaceTabs.vue'
import FullPage from '@/components/FullPage.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import WorkspacePage from '@/pages/Workspace.vue'
import { useScrollMemory } from '@/scroll'
import { resolveTabs, useLastWorkspace, useTabs } from '@/tabs'
import { inStandardOrder, useWorkspaces, Workspace } from '@/workspace'

const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const navigation = useNavigation()
const tabs = useTabs()
const workspaces = useWorkspaces()

const placement = engineRoot
const placementAddress = Address.parse(engineRoot)

const canManage = $computed(() => access.canManage(placement))

// Adding a workspace here needs only view, because a user without manage gets a private one, which
// nobody else sees.
const canCreate = $computed(() => access.canView(placement))

// The deployment's landing page. Deliberately narrower than every workspace at the engine root,
// because this is what a new user inherits rather than everything that happens to live here.
let defaults = $ref<Workspace[]>([])

async function refreshDefaults() {
  const listed = await workspaces.listScoped(placementAddress)
  defaults = inStandardOrder(listed.filter((workspace) => workspace.show_when_logged_out))
}

// Home may hold a workspace placed on any component, so its tabs resolve against everything the
// user can see rather than against the engine root's own list.
const homeWorkspaces = $computed(() =>
  resolveTabs(
    defaults,
    tabs.setFor(placement),
    (workspace) => workspace.id,
    workspaces.all as Workspace[]
  )
)

// A tab strip that holds workspaces from more than one placement needs each tab to say where it
// came from. One that does not would only be repeating itself.
const showPlacement = $computed(() => homeWorkspaces.some((workspace) => !workspace.scope.isEngine))

// Anything the user can see that is not already on the strip, which is what the add button offers.
// Home is not limited to one placement, so this spans every workspace they have access to.
const openableWorkspaces = $computed(() => {
  const shown = new Set(homeWorkspaces.map((workspace) => workspace.id))
  return (workspaces.all as Workspace[]).filter((workspace) => !shown.has(workspace.id))
})

async function openHome(id: string) {
  await tabs.open(placement, id)
  selectWorkspace(id)
}

const lastWorkspace = useLastWorkspace(placement)

const activeWorkspaceId = $computed(() => {
  const value = navigation.route.query.workspace
  return typeof value === 'string' ? value : null
})

// Switching tabs returns to where each workspace was left, the way switching browser tabs does.
useScrollMemory(() => (activeWorkspaceId == null ? null : `${placement}/${activeWorkspaceId}`))

function showWorkspace(id: string) {
  void navigation.replace({ query: { workspace: id } })
}

// Choosing a workspace records it as this strip's last, so home reopens on it. Only a deliberate
// choice records, because the fallback below shows one too and would otherwise overwrite the
// memory with whatever it settled for.
function selectWorkspace(id: string) {
  lastWorkspace.id = id
  showWorkspace(id)
}

async function closeHome(id: string) {
  const remaining = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(placement, id)

  if (activeWorkspaceId !== id) {
    return
  }

  if (remaining.length > 0) {
    selectWorkspace(remaining[0].id)
  } else {
    await navigation.replace({ query: {} })
  }
}

// Closing the rest leaves the kept one showing, whether or not it was the one being looked at.
async function closeOtherHome(id: string) {
  const others = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.closeMany(
    placement,
    others.map((workspace) => workspace.id)
  )
  selectWorkspace(id)
}

// Closing everything leaves home with nothing named, which is its own empty state.
async function closeAllHome() {
  await tabs.closeMany(
    placement,
    homeWorkspaces.map((workspace) => workspace.id)
  )
  await navigation.replace({ query: {} })
}

async function reorderHome(ordered: Workspace[]) {
  await tabs.reorder(
    placement,
    ordered.map((workspace) => workspace.id)
  )
}

function createHome() {
  dialogs.createWorkspace(placement).onOk(async (created: Workspace) => {
    await tabs.open(placement, created.id)
    await refreshDefaults()
    selectWorkspace(created.id)
  })
}

async function importHome(files: File[]) {
  const imported = await workspaces.importWorkspaces(files, {
    scope: placementAddress,
    owner_id: canManage ? null : auth.user?.id,
  })

  await Promise.all(imported.map((workspace) => tabs.open(placement, workspace.id)))
  await refreshDefaults()
  if (imported.length > 0) {
    selectWorkspace(imported[0].id)
  }
}

await tabs.load()
await refreshDefaults()

// A first login starts from what the deployment shows when logged out, so a new person lands on
// the same view an anonymous visitor sees and then makes it their own. Seeding is skipped once the
// user has arranged this strip, so it never overwrites their own choices.
if (!tabs.isTouched(placement)) {
  await tabs.seed(
    placement,
    defaults.map((workspace) => workspace.id)
  )
}

watch(
  () => workspaces.all,
  () => {
    void refreshDefaults()
  }
)

// Landing on home reopens whichever workspace was last shown here, falling back to the first tab
// when that one is gone. Closing the last one clears the query entirely, which is what tells that
// apart from arriving with nothing named.
watch(
  () => [activeWorkspaceId, homeWorkspaces] as const,
  ([active, listed]) => {
    if (active != null || listed.length === 0 || navigation.route.query.workspace !== undefined) {
      return
    }

    // The remembered workspace may be one placed on a component, which appears on the strip only
    // once the full list has landed. Waiting for it costs nothing when there is nothing to wait
    // for, since a user with no workspaces has an empty strip and is already handled above.
    if (workspaces.all.length === 0) {
      return
    }

    const remembered = listed.find((workspace) => workspace.id === lastWorkspace.id)
    showWorkspace((remembered ?? listed[0]).id)
  },
  { immediate: true }
)
</script>

<template>
  <workspace-page v-if="activeWorkspaceId != null" :id="activeWorkspaceId">
    <template #header-prepend="{ actions, state }">
      <component-workspace-tabs
        :active="activeWorkspaceId"
        :active-actions="actions"
        :active-state="state"
        :can-create="canCreate"
        :can-manage="canManage"
        class="q-ml-sm"
        :openable="openableWorkspaces"
        :show-placement="showPlacement"
        :workspaces="homeWorkspaces"
        @close="closeHome"
        @close-all="closeAllHome"
        @close-others="closeOtherHome"
        @create="createHome"
        @import="importHome"
        @open="openHome"
        @reorder="reorderHome"
        @select="selectWorkspace"
      />
    </template>
  </workspace-page>
  <full-page v-else-if="homeWorkspaces.length > 0 || canCreate" dense>
    <template #header-append>
      <component-workspace-tabs
        :active="activeWorkspaceId"
        :can-create="canCreate"
        :can-manage="canManage"
        class="q-ml-sm"
        :openable="openableWorkspaces"
        :show-placement="showPlacement"
        :workspaces="homeWorkspaces"
        @close="closeHome"
        @close-all="closeAllHome"
        @close-others="closeOtherHome"
        @create="createHome"
        @import="importHome"
        @open="openHome"
        @reorder="reorderHome"
        @select="selectWorkspace"
      />
    </template>
    <div class="q-py-xl text-center">
      <div class="q-mb-md" :style="{ opacity: 0.6 }">
        <template v-if="openableWorkspaces.length > 0">
          Nothing open. Open a workspace from the tab bar above.
        </template>
        <template v-else>No workspaces yet.</template>
      </div>
      <q-btn
        v-if="canCreate"
        color="primary"
        :icon="icons.add"
        label="Create Workspace"
        no-caps
        outline
        @click="createHome"
      />
    </div>
  </full-page>
  <full-page v-else title="Home">
    <div class="q-py-xl text-center" :style="{ opacity: 0.6 }">No workspaces yet.</div>
  </full-page>
</template>
