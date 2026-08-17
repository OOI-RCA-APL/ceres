<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { watch } from 'vue'

import { useAccess } from '@/api/access'
import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import CComponentWorkspaceStrip, {
  overviewFillHeight,
} from '@/components/c-component-workspace-strip.vue'
import { appHeaderHeight, pageHeaderHeight } from '@/components/c-full-page.vue'
import CWorkspace from '@/components/c-workspace.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { usePersisted } from '@/persistence'
import { useScrollMemory } from '@/scroll'
import { resolveTabs, useLastWorkspace, useRequestedWorkspaces, useTabs } from '@/tabs'
import { inStandardOrder, useWorkspaces, type Workspace } from '@/workspace'

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

async function openHome(id: string) {
  await tabs.open(placement, id)
  revealHome(id)
}

// A copy belongs next to its original so the strip reads as the original followed by its copy.
async function openBesideHome(afterId: string, id: string) {
  await tabs.openBeside(
    placement,
    id,
    afterId,
    homeWorkspaces.map((workspace) => workspace.id),
  )
  revealHome(id)
}

const lastWorkspace = useLastWorkspace(placement)

// Held here rather than read from the address. The address asks for a workspace and is cleared
// once it has been given one so what is showing is this page's own state from then on.
let activeWorkspaceId = $ref<string | null>(null)

// What the address is currently asking for, which the fallback below waits for rather than
// choosing a workspace that is about to be replaced.
const requested = useRequestedWorkspaces(navigation.router)
const requestedIds = $computed(() => requested.workspace)

let overviewElement = $ref<HTMLElement | null>(null)

// Unsized, the overview reaches to where the strip rests on the bottom edge. Dragged, it is that
// height exactly, so shortening it takes effect rather than being floored back to the fill.
const overviewHeightStyle = $computed(() => ({
  height:
    persisted.overviewSize != null
      ? `${persisted.overviewSize}px`
      : overviewFillHeight(workspaceStickyTop),
}))

// What a drag starts from while the overview is still unsized, read off the box rather than
// recomputed, so the first move carries on from the height already on screen.
let overviewMeasuredHeight = $ref(0)
useResizeObserver($$(overviewElement), ([entry]) => {
  if (entry != null) {
    overviewMeasuredHeight = entry.contentRect.height
  }
})

// Zero until the box has been measured, and the handle waits for a real size rather than mounting
// on that and storing the minimum it clamps up to.
const overviewDragSize = $computed(() => persisted.overviewSize ?? overviewMeasuredHeight)

// Followed reactively so the floating action bar can yield while the strip rests at the
// bottom edge.
let stripRef = $ref<InstanceType<typeof CComponentWorkspaceStrip> | null>(null)
const stripDocked = $computed(() => stripRef?.docked ?? false)

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
  pinnedAt,
)

// Whatever is showing is what home reopens on so it is recorded here rather than at each of the
// places that can choose one.
function showWorkspace(id: string) {
  activeWorkspaceId = id
  lastWorkspace.id = id
}

// Reached for the tab strip's active workspace actions and state, drawn on this page.
let workspaceRef = $ref<InstanceType<typeof CWorkspace> | null>(null)

/** Show a workspace the user explicitly chose, bringing hidden content back and scrolling to
it when the strip is stuck to the bottom edge. The fallback selections after a close keep to
`showWorkspace`. */
function revealHome(id: string) {
  persisted.workspaceCollapsed = false
  showWorkspace(id)
  void stripRef?.scrollToPin(pinnedAt())
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

  // Only this page's own request is taken back out, leaving whatever else the bar carries.
  requested.workspace = []
  if (opening.length === 0) {
    return
  }

  await tabs.openMany(placement, opening)
  showWorkspace(opening[0] as string)
}

async function closeHome(id: string) {
  const remaining = homeWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(placement, id)

  if (activeWorkspaceId !== id) {
    return
  }

  activeWorkspaceId = remaining.length > 0 ? (remaining[0]?.id ?? null) : null
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
    others.map((workspace) => workspace.id),
  )
  showWorkspace(id)
}

// Closing everything leaves home showing nothing, which is its own empty state.
async function closeAllHome() {
  await tabs.closeMany(
    placement,
    homeWorkspaces.map((workspace) => workspace.id),
  )
  activeWorkspaceId = null
}

async function reorderHome(ordered: Workspace[]) {
  await tabs.reorder(
    placement,
    ordered.map((workspace) => workspace.id),
  )
}

function createHome() {
  dialogs.createWorkspace(placement).onOk(async (created) => {
    await tabs.open(placement, created.id)
    await refreshPlaced()
    revealHome(created.id)
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
    revealHome((imported[0] as Workspace).id)
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

// Watched rather than read once because home stays mounted while an action elsewhere sends a
// workspace here, which arrives as a change of address rather than as a fresh visit.
watch(
  () => [requestedIds, workspaces.all] as const,
  () => {
    void adoptRequested()
  },
  { immediate: true },
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
    showWorkspace((remembered ?? (listed[0] as Workspace)).id)
  },
  { immediate: true },
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
    <template v-else>
      <div v-if="!persisted.overviewCollapsed" ref="overviewElement" class="relative">
        <!-- Never less than what puts the strip at the bottom edge, where it rests until the
        page is scrolled. With workspace content hidden the overview takes its full height. -->
        <!-- The maximum applies only when nothing was dragged onto the panel, the inline height
        below taking over once one has been. -->
        <div
          class="max-h-[calc(100vh-92px)] overflow-x-hidden overflow-y-auto"
          :style="
            activeWorkspaceId != null && !persisted.workspaceCollapsed
              ? overviewHeightStyle
              : undefined
          "
        >
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
            @close="closeHome"
            @open="showWorkspace"
            @open-beside="openBesideHome"
            @share="shareHome"
          />
        </div>
        <c-resize-handle
          v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed && overviewDragSize > 0"
          class="absolute bottom-0 left-0"
          direction="vertical"
          :max="800"
          :min="120"
          :model-value="overviewDragSize"
          @update:model-value="(value: number) => (persisted.overviewSize = value)"
        />
      </div>

      <!-- The strip sits in flow between the overview and the workspace, and sticks at both
      edges so it is always on screen, pinning under the header the way it always has and
      resting at the bottom while its own place is still below the fold. -->
      <c-component-workspace-strip
        v-if="homeWorkspaces.length > 0 || canCreate"
        ref="stripRef"
        v-model:collapsed="persisted.workspaceCollapsed"
        :sticky-top="workspaceStickyTop"
      >
        <template #default="{ docked, trailingInset }">
          <c-component-workspace-tabs
            :active="activeWorkspaceId"
            :active-actions="workspaceRef?.headerActions"
            :active-state="workspaceRef?.headerState"
            :can-create="canCreate"
            :can-manage="canManage"
            :docked="docked"
            :openable="openableWorkspaces"
            :show-placement="showPlacement"
            :trailing-inset="trailingInset"
            :workspaces="homeWorkspaces"
            @close="closeHome"
            @close-all="closeAllHome"
            @close-others="closeOtherHome"
            @create="createHome"
            @import="importHome"
            @open="openHome"
            @open-beside="openBesideHome"
            @reorder="reorderHome"
            @select="revealHome"
            @share="shareHome"
          />
        </template>
      </c-component-workspace-strip>
      <!-- Deliberately not keyed on the workspace ID. The workspace context follows its ID, so
      switching tabs updates this page in place. -->
      <c-workspace
        v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed"
        :id="activeWorkspaceId"
        ref="workspaceRef"
        :sticky-top="workspaceStickyTop"
        :strip-docked="stripDocked"
        @duplicated="openBesideHome"
      />
    </template>
  </c-full-page>
</template>
