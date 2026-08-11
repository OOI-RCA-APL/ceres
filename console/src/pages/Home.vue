<script lang="ts" setup>
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import ComponentWorkspaceTabs from '@/components/ComponentWorkspaceTabs.vue'
import ComponentWorkspacesSection from '@/components/ComponentWorkspacesSection.vue'
import FullPage, { appHeaderHeight, pageHeaderHeight } from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import WorkspacePage from '@/pages/Workspace.vue'
import { usePersisted } from '@/persistence'
import { useScrollMemory } from '@/scroll'
import { requestedWorkspaces, resolveTabs, useLastWorkspace, useTabs } from '@/tabs'
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

// Adding a workspace here needs only view because a user without manage gets a private one, which
// nobody else sees.
const canCreate = $computed(() => access.canView(placement))

// The tab strip pins under this page's own header so scrolling the overview away leaves the tabs
// directly beneath it.
const workspaceStickyTop = appHeaderHeight + pageHeaderHeight

// Declared up here because the scroll memory below reads the overview's own state as it starts.
const persisted = usePersisted({
  schema: ({ object, boolean, number }) =>
    object({
      overviewCollapsed: boolean().default(false),
      overviewHeight: number().default(320),
    }),
  methods: [{ type: 'local-storage', key: 'home-overview' }],
})

// Every workspace placed on the engine root that the caller can see, which the overview lists.
// These are the deployment's own workspaces rather than any one component's.
let placedWorkspaces = $ref<Workspace[]>([])

// What a new user's tab strip starts from. Only the workspaces flagged `show_when_logged_out`.
const defaults = $computed(() =>
  placedWorkspaces.filter((workspace) => workspace.show_when_logged_out)
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
    workspaces.all as Workspace[]
  )
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

async function openHome(id: string) {
  await tabs.open(placement, id)
  showWorkspace(id)
}

// A copy belongs next to its original so the strip reads as the original followed by its copy.
async function openBesideHome(afterId: string, id: string) {
  await tabs.openBeside(
    placement,
    id,
    afterId,
    homeWorkspaces.map((workspace) => workspace.id)
  )
  showWorkspace(id)
}

const lastWorkspace = useLastWorkspace(placement)

// Held here rather than read from the address. The address asks for a workspace and is cleared
// once it has been given one so what is showing is this page's own state from then on.
let activeWorkspaceId = $ref<string | null>(null)

// What the address is currently asking for, which the fallback below waits for rather than
// choosing a workspace that is about to be replaced.
const requestedIds = $computed(() => requestedWorkspaces(navigation.route.query))

let overviewElement = $ref<HTMLElement | null>(null)

/** How far the page must be scrolled for the tab strip to have pinned under the header.

Measured from the overview, which sits above the strip and is never itself pinned, so its box is
reliable. The strip's own box stops moving once it pins. With no overview showing, the strip is at
the top from the start and there is nothing to scroll past.
*/
function pinnedAt(): number {
  if (persisted.overviewCollapsed || overviewElement == null) {
    return 0
  }

  const bottom = overviewElement.getBoundingClientRect().bottom + window.scrollY
  return Math.max(0, bottom - workspaceStickyTop)
}

/** Whether moving the page on a tab switch would be welcome.

With the overview showing and the page still above the pin, the overview is what is being read, so
jumping to wherever another workspace was left moves all of that out from under. Past the pin the
overview is out of view and the page is the workspace, which is when returning to where it was left
is the helpful thing.
*/
function isScrollSettled(): boolean {
  return window.scrollY >= pinnedAt()
}

// Switching tabs returns to where each workspace was left, the way switching browser tabs does,
// and never above the pin so a strip that was stuck to the header stays exactly where it was
// rather than dropping back down the page.
useScrollMemory(
  () => (activeWorkspaceId == null ? null : `${placement}/${activeWorkspaceId}`),
  isScrollSettled,
  pinnedAt
)

// With tabs to show but no workspace beneath them, the strip sits at the bottom of the screen
// rather than floating below the overview with empty space under it. An empty strip has nothing to
// hold down there, and collapsing the overview leaves nothing to push it away from so in either
// case it goes back to sitting under the overview.
const pinTabs = $computed(
  () => activeWorkspaceId == null && !persisted.overviewCollapsed && homeWorkspaces.length > 0
)

// Whatever is showing is what home reopens on so it is recorded here rather than at each of the
// places that can choose one.
function showWorkspace(id: string) {
  activeWorkspaceId = id
  lastWorkspace.id = id
}

/** Give the address what it asked for, then take the request back out of it.

Workspaces named there join the strip if they were not already on it so a link behaves the same as
opening them from the strip itself, and the first of them is what ends up showing.

Nothing is done until the full list has landed because a link can arrive before it does and an
identifier that matches nothing must not write a tab that resolves to nothing.
*/
async function adoptRequested() {
  if (requestedIds.length === 0) {
    return
  }

  const known = new Set((workspaces.all as Workspace[]).map((workspace) => workspace.id))
  const opening = requestedIds.filter((id) => known.has(id))
  if (opening.length === 0 && workspaces.all.length === 0) {
    return
  }

  await navigation.replace({ query: {} })
  if (opening.length === 0) {
    return
  }

  await tabs.openMany(placement, opening)
  showWorkspace(opening[0])
}

async function closeHome(id: string) {
  const remaining = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(placement, id)

  if (activeWorkspaceId !== id) {
    return
  }

  activeWorkspaceId = remaining.length > 0 ? remaining[0].id : null
  if (activeWorkspaceId != null) {
    lastWorkspace.id = activeWorkspaceId
  }
}

function shareHome(ids: string[]) {
  void workspaces.copyLink(placement, ids)
}

// Closing the rest leaves the kept one showing, whether or not it was the one being looked at.
async function closeOtherHome(id: string) {
  const others = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.closeMany(
    placement,
    others.map((workspace) => workspace.id)
  )
  showWorkspace(id)
}

// Closing everything leaves home showing nothing, which is its own empty state.
async function closeAllHome() {
  await tabs.closeMany(
    placement,
    homeWorkspaces.map((workspace) => workspace.id)
  )
  activeWorkspaceId = null
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
    await refreshPlaced()
    showWorkspace(created.id)
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
    showWorkspace(imported[0].id)
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
      defaults.map((workspace) => workspace.id)
    )
  }
}

watch(
  () => workspaces.all,
  () => {
    void refreshPlaced()
  }
)

// Watched rather than read once because home stays mounted while an action elsewhere sends a
// workspace here, which arrives as a change of address rather than as a fresh visit.
watch(
  () => [requestedIds, workspaces.all] as const,
  () => {
    void adoptRequested()
  },
  { immediate: true }
)

// With nothing showing, home opens on whichever workspace it last showed, falling back to the
// first tab when that one is gone. An empty strip has nothing to open on, which is home's own
// empty state, and a request still pending is about to name one itself.
watch(
  () => [activeWorkspaceId, homeWorkspaces, requestedIds] as const,
  ([active, listed, requested]) => {
    if (active != null || listed.length === 0 || requested.length > 0) {
      return
    }

    // The remembered workspace may be one placed on a component, which appears on the strip only
    // once the full list has landed. Waiting for it costs nothing when there is nothing to wait
    // for since a user with no workspaces has an empty strip and is already handled above.
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
  <full-page :fill="pinTabs || auth.user == null" title="Home">
    <template v-if="auth.user != null" #header-append>
      <q-space />
      <!-- Flush with the right edge of the widgets below, whose cards sit half a gutter in. -->
      <q-btn
        class="q-mr-sm"
        :color="persisted.overviewCollapsed ? undefined : 'primary'"
        dense
        flat
        :icon="persisted.overviewCollapsed ? icons.menuDown : icons.menuUp"
        :icon-right="icons.overview"
        size="sm"
        @click="persisted.overviewCollapsed = !persisted.overviewCollapsed"
      >
        <q-tooltip class="bg-primary text-white">
          {{ persisted.overviewCollapsed ? 'Show' : 'Hide' }} Details
        </q-tooltip>
      </q-btn>
    </template>

    <div v-if="auth.user == null" class="col column flex flex-center text-grey-6">
      <q-icon :name="icons.locked" size="32px" />
      <q-btn class="q-mt-md" color="primary" label="Log In" no-caps to="/login" unelevated />
    </div>
    <template v-else>
      <div v-if="!persisted.overviewCollapsed" ref="overviewElement" class="relative-position">
        <div
          :class="[$style.overviewContent, 'scroll']"
          :style="
            activeWorkspaceId != null ? { height: `${persisted.overviewHeight}px` } : undefined
          "
        >
          <!-- The engine root's own workspaces, which are the deployment's rather than any one
          component's. A workspace placed on a component is reached from that component, and
          appears here only once it has been opened as a tab below. -->
          <component-workspaces-section
            :can-manage="canManage"
            class="q-pa-md"
            :open-ids="homeWorkspaces.map((workspace) => workspace.id)"
            :placement="placement"
            :workspaces="placedWorkspaces"
            @close="closeHome"
            @open="showWorkspace"
            @open-beside="openBesideHome"
            @share="shareHome"
          />
        </div>
        <resize-handle
          v-if="activeWorkspaceId != null"
          v-model="persisted.overviewHeight"
          :class="$style.overviewResizeHandle"
          direction="vertical"
          :max="800"
          :min="120"
        />
      </div>

      <!-- Deliberately not keyed on the workspace ID. The workspace context follows its ID, so
      switching tabs updates this page in place and leaves the tab strip in its header mounted. -->
      <workspace-page
        v-if="activeWorkspaceId != null"
        :id="activeWorkspaceId"
        :sticky-top="workspaceStickyTop"
        @duplicated="openBesideHome"
      >
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
            @open-beside="openBesideHome"
            @reorder="reorderHome"
            @select="showWorkspace"
            @share="shareHome"
          />
        </template>
      </workspace-page>
      <div v-else-if="homeWorkspaces.length > 0 || canCreate" :class="pinTabs && $style.pinnedTabs">
        <q-separator />
        <component-workspace-tabs
          :active="activeWorkspaceId"
          :can-create="canCreate"
          :can-manage="canManage"
          class="q-px-sm q-py-xs"
          :openable="openableWorkspaces"
          :show-placement="showPlacement"
          :workspaces="homeWorkspaces"
          @close="closeHome"
          @close-all="closeAllHome"
          @close-others="closeOtherHome"
          @create="createHome"
          @import="importHome"
          @open="openHome"
          @open-beside="openBesideHome"
          @reorder="reorderHome"
          @select="showWorkspace"
          @share="shareHome"
        />
      </div>
    </template>
  </full-page>
</template>

<style lang="scss" module>
// With a workspace below, the panel takes the height dragged onto it, set inline. On its own it
// grows with its content up to what is left of the viewport, then scrolls.
.overviewContent {
  overflow-x: hidden;
  max-height: calc(100vh - 92px);
}

.pinnedTabs {
  margin-top: auto;
}

.overviewResizeHandle {
  position: absolute;
  bottom: 0;
  left: 0;
}
</style>
