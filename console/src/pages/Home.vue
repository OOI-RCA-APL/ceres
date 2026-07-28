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
import { resolveTabs, useTabs } from '@/tabs'
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

const activeWorkspaceId = $computed(() => {
  const value = navigation.route.query.workspace
  return typeof value === 'string' ? value : null
})

function selectWorkspace(id: string) {
  void navigation.replace({ query: { workspace: id } })
}

async function closeHome(id: string) {
  const remaining = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(placement, id)

  if (activeWorkspaceId === id) {
    await navigation.replace({ query: remaining.length > 0 ? { workspace: remaining[0].id } : {} })
  }
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

// Landing on home opens the first tab. Closing the last one clears the query entirely, which is
// what tells that apart from arriving with nothing named.
watch(
  () => [activeWorkspaceId, homeWorkspaces] as const,
  ([active, listed]) => {
    if (active == null && listed.length > 0 && navigation.route.query.workspace === undefined) {
      selectWorkspace(listed[0].id)
    }
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
        :show-placement="showPlacement"
        :workspaces="homeWorkspaces"
        @close="closeHome"
        @create="createHome"
        @import="importHome"
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
        :show-placement="showPlacement"
        :workspaces="homeWorkspaces"
        @close="closeHome"
        @create="createHome"
        @import="importHome"
        @reorder="reorderHome"
        @select="selectWorkspace"
      />
    </template>
    <div class="q-py-xl text-center">
      <div class="q-mb-md" :style="{ opacity: 0.6 }">No workspaces yet.</div>
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
