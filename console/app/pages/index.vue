<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import CWorkspaceHost from '@/components/c-workspace-host.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { resolveTabs, useTabs } from '@/tabs'
import { inStandardOrder, useWorkspaces, type Workspace } from '@/workspace'

const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const tabs = useTabs()
const workspaces = useWorkspaces()

const placement = engineRoot
const placementAddress = Address.parse(engineRoot)

const canManage = $computed(() => access.canManage(placement))

// Adding a workspace here needs only view because a user without manage gets a private one, which
// nobody else sees.
const canCreate = $computed(() => access.canView(placement))

const persisted = usePersisted({
  schema: ({ object, boolean, number }) =>
    object({
      overviewCollapsed: boolean().default(false),
      overviewSize: number().nullable().default(null),
      workspaces: boolean().default(true),
      workspaceCollapsed: boolean().default(false),
    }),
  methods: [{ type: 'local-storage', key: 'home-overview' }],
})

// Every workspace placed on the engine root that the caller can see, which the overview lists.
// These are the deployment's own workspaces rather than any one component's.
let placedWorkspaces = $ref<Workspace[]>([])

// What a new user's tab strip starts from. Only the workspaces flagged `show_when_logged_out`.
const defaults = $computed(() =>
  placedWorkspaces.filter((workspace) => workspace.show_when_logged_out),
)

async function refreshPlaced() {
  placedWorkspaces = inStandardOrder(await workspaces.listScoped(placementAddress))
}

// Home may hold a workspace placed on any component so its tabs resolve against everything the
// user can see rather than against the engine root's own list.
const homeWorkspaces = $computed(() =>
  resolveTabs(
    defaults,
    tabs.setFor(placement),
    (workspace) => workspace.id,
    workspaces.all as Workspace[],
  ),
)

// A tab strip that holds workspaces from more than one placement needs each tab to say where it
// came from. One that does not would only be repeating itself.
const showPlacement = $computed(() => homeWorkspaces.some((workspace) => !workspace.scope.isEngine))

// Anything the user can see that is not already on the strip, which the add button offers.
// Home is not limited to one placement so this spans every workspace they have access to.
const openableWorkspaces = $computed(() => {
  const shown = new Set(homeWorkspaces.map((workspace) => workspace.id))
  return (workspaces.all as Workspace[]).filter((workspace) => !shown.has(workspace.id))
})

let hostRef = $ref<InstanceType<typeof CWorkspaceHost> | null>(null)

function shareHome(ids: string[]) {
  void workspaces.copyLink(placement, ids)
}

function createHome() {
  dialogs.createWorkspace(placement).onOk(async (created) => {
    await tabs.open(placement, created.id)
    await refreshPlaced()
    hostRef?.reveal(created.id)
  })
}

async function importHome(files: File[]) {
  const imported = await workspaces.importWorkspaces(files, {
    scope: placementAddress,
    owner_id: canManage ? null : auth.user?.id,
  })

  await Promise.all(imported.map((workspace) => tabs.open(placement, workspace.id)))
  await refreshPlaced()
  if (imported.length > 0) {
    hostRef?.reveal((imported[0] as Workspace).id)
  }
}

// Logged out, there is nothing to fetch and nothing to seed. The template shows a sign-in
// state instead.
if (auth.user != null) {
  await tabs.load()
  await refreshPlaced()

  // A first login seeds this strip from the workspaces flagged `show_when_logged_out`. Seeding
  // stops once the user has arranged the strip, so it never overwrites their own choices.
  if (!tabs.isTouched(placement)) {
    await tabs.seed(
      placement,
      defaults.map((workspace) => workspace.id),
    )
  }
}

watch(
  () => workspaces.all,
  () => {
    void refreshPlaced()
  },
)
</script>

<template>
  <c-full-page fill title="Home">
    <template v-if="auth.user != null" #header-append>
      <div class="flex-1" />
      <!-- Flush with the right edge of the widgets below, whose cards sit half a gutter in. -->
      <c-tooltip :text="`${persisted.overviewCollapsed ? 'Show' : 'Hide'} Details`">
        <c-button
          class="mr-2"
          :color="persisted.overviewCollapsed ? 'neutral' : 'primary'"
          :icon="persisted.overviewCollapsed ? icons.menuDown : icons.menuUp"
          size="xs"
          :trailing-icon="icons.overview"
          variant="ghost"
          @click="persisted.overviewCollapsed = !persisted.overviewCollapsed"
        />
      </c-tooltip>
    </template>

    <div
      v-if="auth.user == null"
      class="flex flex-1 flex-col items-center justify-center gap-4 text-muted"
    >
      <c-icon :name="icons.locked" size="32" />
      <c-button color="primary" label="Log In" to="/login" />
    </div>
    <c-workspace-host
      v-else
      ref="hostRef"
      v-model:overview-collapsed="persisted.overviewCollapsed"
      v-model:overview-size="persisted.overviewSize"
      v-model:workspace-collapsed="persisted.workspaceCollapsed"
      :adoptable="workspaces.all as Workspace[]"
      :can-create="canCreate"
      :can-manage="canManage"
      :openable="openableWorkspaces"
      :placement="placement"
      :show-placement="showPlacement"
      :workspaces="homeWorkspaces"
      @create="createHome"
      @import="importHome"
      @share="shareHome"
    >
      <template #overview="{ openListed }">
        <!-- The engine root's own workspaces, which are the deployment's rather than any one
        component's. A workspace placed on a component is reached from that component, and
        appears here only once it has been opened as a tab below. -->
        <c-component-workspaces-section
          v-model:expanded="persisted.workspaces"
          :can-manage="canManage"
          class="p-4"
          collapsible
          :open-ids="homeWorkspaces.map((workspace) => workspace.id)"
          :placement="placement"
          :workspaces="placedWorkspaces"
          @close="(id: string) => hostRef?.close(id)"
          @open="openListed"
          @open-beside="(afterId: string, id: string) => hostRef?.openBeside(afterId, id)"
          @share="shareHome"
        />
      </template>
    </c-workspace-host>
  </c-full-page>
</template>
