<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { until, useMediaQuery } from '@vueuse/core'
import { upperFirst } from 'lodash-es'
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { stringify } from 'yaml'

import { useAccess } from '@/api/access'
import { Address } from '@/api/address'
import { useAuth } from '@/api/auth'
import { ConnectionInfo, ConnectionStateInfo, JobInfo, ProcedureInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { Connectivity } from '@/api/shared'
import CommonText from '@/components/CommonText.vue'
import ComponentParticlesSection from '@/components/ComponentParticlesSection.vue'
import ComponentWorkspaceStrip, {
  overviewFillHeight,
} from '@/components/ComponentWorkspaceStrip.vue'
import ComponentWorkspaceTabs from '@/components/ComponentWorkspaceTabs.vue'
import ComponentWorkspacesSection from '@/components/ComponentWorkspacesSection.vue'
import FullPage, { appHeaderHeight, pageHeaderHeight } from '@/components/FullPage.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import WorkspacePage from '@/pages/Workspace.vue'
import { usePersisted } from '@/persistence'
import { useScrollMemory } from '@/scroll'
import { requestedWorkspaces, resolveTabs, useLastWorkspace, useTabs } from '@/tabs'
import { utc } from '@/time'
import { highlight } from '@/utilities'
import { inStandardOrder, openedRowFor, useWorkspaces, Widget, Workspace } from '@/workspace'

const engine = useEngine()
const access = useAccess()
const auth = useAuth()
const dialogs = useDialogs()
const navigation = useNavigation()
const notify = useNotify()
const route = useRoute()
const tabs = useTabs()
const workspaces = useWorkspaces()

const address = $computed(() => new Address(route.params.address as string))
const component = $computed(() => engine.components.get(address))

const effectiveAccess = $computed(() => access.levelFor(address.toString()))

const canManage = $computed(() => access.canManage(address.toString()))

// Adding a workspace here needs only view because a user without manage gets a private one,
// which nobody else sees.
const canCreate = $computed(() => access.canView(address.toString()))

// The tab strip pins under this page's own header so scrolling the overview away leaves the
// component named above and its tabs directly beneath.
const workspaceStickyTop = appHeaderHeight + pageHeaderHeight

// Below this width the overview's two columns stack into one, which makes it roughly twice as
// tall. A height dragged on a wide screen then clips it mid-item so there it sizes to its own
// content instead and the drag handle goes away with the drag.
const overviewColumnsMin = 720
const overviewStacks = useMediaQuery(`(max-width: ${overviewColumnsMin - 1}px)`)

// A collapsed configuration leaves its column as one closed bar with the rest of the panel empty
// beside it so the workspaces move under it and the reference lists get the width to themselves.
// Stacked there is only one column, and expanded the configuration fills its own.
const workspacesUnderConfig = $computed(
  () => configHighlighted != null && !overviewStacks && !persisted.configuration
)

// Persist each drawer's open state per component address. The page remounts on navigation between
// components (the page container is keyed by route path) so this re-reads for the new address.
// Declared up here because the scroll memory below reads the overview's own state as it starts.
const persisted = usePersisted({
  schema: ({ object, boolean, number, record, string }) =>
    object({
      configuration: boolean().default(true),
      workspaces: boolean().default(true),
      connections: boolean().default(false),
      jobs: boolean().default(false),
      particles: boolean().default(false),
      particleTypes: record(string(), boolean()).default({}),
      queries: boolean().default(false),
      actions: boolean().default(false),
      overviewCollapsed: boolean().default(false),
      overviewHeight: number().default(320),
      workspaceCollapsed: boolean().default(false),
    }),
  methods: computed(() => [
    { type: 'local-storage' as const, key: ['component-detail-drawers', address] },
  ]),
})

// The shared default set for this component, in standard order.
let placedWorkspaces = $ref<Workspace[]>([])

// What this user's strip actually shows. The defaults are what someone who has never touched this
// strip sees, and their own set takes over from there.
const scopedWorkspaces = $computed(() =>
  resolveTabs(placedWorkspaces, tabs.setFor(address.toString()), (workspace) => workspace.id)
)

// Placed here but not in the strip, which the add button offers before creating one.
const openableWorkspaces = $computed(() => {
  const shown = new Set(scopedWorkspaces.map((workspace) => workspace.id))
  return placedWorkspaces.filter((workspace) => !shown.has(workspace.id))
})

async function openScoped(id: string) {
  await tabs.open(address.toString(), id)
  revealScoped(id)
}

// A copy belongs next to its original so the strip reads as the original followed by its copy.
async function openBesideScoped(afterId: string, id: string) {
  await refreshScoped()
  await tabs.openBeside(
    address.toString(),
    id,
    afterId,
    scopedWorkspaces.map((workspace) => workspace.id)
  )
  revealScoped(id)
}

const lastWorkspace = useLastWorkspace(() => address.toString())

// Held here rather than read from the address. The address asks for a workspace and is cleared
// once it has been given one so what is showing is this page's own state from then on. Without a
// request the page falls back to whichever workspace was last shown here so a component with
// workspaces opens on one rather than on a bare overview.
let activeWorkspaceId = $ref<string | null>(null)

// What the address is currently asking for, which the fallback below waits for rather than
// choosing a workspace that is about to be replaced.
const requestedIds = $computed(() => requestedWorkspaces(navigation.route.query))

let overviewElement = $ref<HTMLElement | null>(null)

// The dragged overview height, never less than what puts the strip at the bottom edge.
const overviewHeightStyle = $computed(() => ({
  height: overviewFillHeight(workspaceStickyTop, persisted.overviewHeight),
}))

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
overview is out of view and the page is the workspace, which is when returning to where it was
left is the helpful thing.
*/
function isScrollSettled(): boolean {
  return window.scrollY >= pinnedAt()
}

// Switching tabs returns to where each workspace was left, the way switching browser tabs does,
// and never above the pin so a strip that was stuck to the header stays exactly where it was
// rather than dropping back down the page.
useScrollMemory(
  () => (activeWorkspaceId == null ? null : `${address.toString()}/${activeWorkspaceId}`),
  isScrollSettled,
  pinnedAt
)

// Whatever is showing is what this component reopens on so it is recorded here rather than at
// each of the places that can choose one.
function showWorkspace(id: string) {
  activeWorkspaceId = id
  lastWorkspace.id = id
}

// Followed reactively so the floating action bar can yield while the strip rests at the
// bottom edge.
let stripRef = $ref<InstanceType<typeof ComponentWorkspaceStrip> | null>(null)
const stripDocked = $computed(() => stripRef?.docked ?? false)

/** Show a workspace the user explicitly chose, bringing hidden content back and scrolling to
it when the strip is stuck at the bottom edge. The fallback selections after a close keep to
`showWorkspace` so a context menu action or a drag never unhides anything. */
function revealScoped(id: string) {
  persisted.workspaceCollapsed = false
  showWorkspace(id)
  void stripRef?.scrollToPin(pinnedAt())
}

// Reached to land a chart built from the particles section directly on the open workspace's
// live working copy.
let workspacePageRef = $ref<InstanceType<typeof WorkspacePage> | null>(null)

/** Give the address what it asked for, then take the request back out of it.

Workspaces named there join this component's strip if they were not already on it so a link
behaves the same as opening them from the strip itself, and the first of them is what ends up
showing.

Only a workspace placed here can join because the strip resolves against this component's own
list and would drop anything else. Nothing is done until that list has landed since a link can
arrive before it does.
*/
async function adoptRequested() {
  if (requestedIds.length === 0) {
    return
  }

  const placed = new Set(placedWorkspaces.map((workspace) => workspace.id))
  const opening = requestedIds.filter((id) => placed.has(id))
  if (opening.length === 0 && placedWorkspaces.length === 0) {
    return
  }

  await navigation.replace({ query: {} })
  if (opening.length === 0) {
    return
  }

  await tabs.openMany(address.toString(), opening)
  showWorkspace(opening[0])
}

function shareScoped(ids: string[]) {
  void workspaces.copyLink(address.toString(), ids)
}

async function refreshScoped() {
  placedWorkspaces = inStandardOrder(await workspaces.listScoped(address))
}

// Dragging positions this user's own tabs. The shared standard order lives in `data.meta.order`
// and is edited from the overview so one user arranging their strip does not rearrange everyone
// else's.
async function reorderScoped(ordered: Workspace[]) {
  await tabs.reorder(
    address.toString(),
    ordered.map((workspace) => workspace.id)
  )
}

// Closing moves to whichever tab takes the closed one's place, or to the bare overview when it was
// the last one. The workspace itself is untouched, which separates closing from deleting.
async function closeScoped(id: string) {
  const remaining = scopedWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.close(address.toString(), id)

  if (activeWorkspaceId !== id) {
    return
  }

  activeWorkspaceId = remaining.length > 0 ? remaining[0].id : null
  if (activeWorkspaceId != null) {
    lastWorkspace.id = activeWorkspaceId
  }
}

// Closing the rest leaves the kept one showing, whether or not it was the one being looked at.
async function closeOtherScoped(id: string) {
  const others = scopedWorkspaces.filter((workspace) => workspace.id !== id)
  await tabs.closeMany(
    address.toString(),
    others.map((workspace) => workspace.id)
  )
  showWorkspace(id)
}

// Closing everything leaves the bare overview, which is where a component with no tabs sits.
async function closeAllScoped() {
  await tabs.closeMany(
    address.toString(),
    scopedWorkspaces.map((workspace) => workspace.id)
  )
  activeWorkspaceId = null
}

// Opening the rest keeps whatever was already showing since opening tabs is not a request to
// look somewhere else. With nothing showing it lands on the first of them.
async function openAllScoped() {
  const opening = openableWorkspaces.map((workspace) => workspace.id)
  await tabs.openMany(address.toString(), opening)

  if (activeWorkspaceId == null && opening.length > 0) {
    showWorkspace(opening[0])
  }
}

// Scoped workspaces are fetched separately from the store's own list so the tabs are refetched
// whenever that list changes. The store refreshes it after every create, update, and delete,
// which covers a workspace being renamed or deleted from the tab shown below.
watch(
  () => workspaces.all,
  () => {
    void refreshScoped()
  }
)

// Watched rather than read once because this page stays mounted while a request arrives as a
// change of address rather than as a fresh visit.
watch(
  () => [requestedIds, placedWorkspaces] as const,
  () => {
    void adoptRequested()
  },
  { immediate: true }
)

// With nothing showing, the page opens on whichever workspace it last showed, falling back to the
// first tab when that one is gone. An empty strip leaves the bare overview, which is where a
// component with no tabs sits, and a request still pending is about to name one itself.
watch(
  () => [activeWorkspaceId, scopedWorkspaces, requestedIds] as const,
  ([active, listed, requested]) => {
    if (active != null || listed.length === 0 || requested.length > 0) {
      return
    }

    const remembered = listed.find((workspace) => workspace.id === lastWorkspace.id)
    showWorkspace((remembered ?? listed[0]).id)
  },
  { immediate: true }
)

function createScoped() {
  dialogs.createWorkspace(address.toString()).onOk(async (created: Workspace) => {
    await refreshScoped()
    revealScoped(created.id)
  })
}

/** Land widgets the particles section built on the workspace open on this component's strip,
through its live editing session so they show immediately as uncommitted changes. With none
open, a private workspace is created and opened to carry them. */
async function createWidgetsScoped(widgets: Widget[]) {
  const [first, ...rest] = widgets
  if (first == null) {
    return
  }

  // Hidden workspace content comes back first, since the widgets land through the mounted page.
  if (activeWorkspaceId != null && persisted.workspaceCollapsed) {
    persisted.workspaceCollapsed = false
    await until(() => workspacePageRef != null).toBeTruthy({ timeout: 5000 })
  }

  // A missing page ref with a workspace open means it failed to mount, and falling through
  // would quietly create a second workspace for widgets meant for the open one.
  if (activeWorkspaceId != null) {
    if (workspacePageRef == null) {
      notify.error('Failed to add the widgets to the open workspace.')
      return
    }

    // The first insert opens a fresh top row and the rest join it beside each other.
    workspacePageRef.insertWidget(first, -1)
    for (const [index, widget] of rest.entries()) {
      workspacePageRef.insertWidget(widget, 0, index + 1)
    }

    await workspacePageRef.revealWidgets(widgets.map((widget) => widget.id))
    return
  }

  try {
    const created = await workspaces.create({
      scope: address.toString(),
      owner_id: auth.user?.id,
      data: {
        layout: [openedRowFor(widgets)],
      },
    })
    await refreshScoped()
    revealScoped(created.id)
  } catch {
    notify.error('Failed to add the widgets.')
  }
}

// A file dropped on this component's strip belongs to this component, and is shared or private on
// the same terms as one created here.
async function importScoped(files: File[]) {
  const imported = await workspaces.importWorkspaces(files, {
    scope: address,
    owner_id: canManage ? null : auth.user?.id,
  })
  await refreshScoped()
  if (imported.length > 0) {
    revealScoped(imported[0].id)
  }
}

await tabs.load()
await refreshScoped()

const queries = $computed(() => component?.procedures.filter((p) => p.type === 'query') ?? [])
const actions = $computed(() => component?.procedures.filter((p) => p.type === 'action') ?? [])

// Each procedure declares its own minimum level, listed here as reference rather than as a
// control since procedures are invoked from workspaces and interfaces instead of this page.
function permissionsLabel(procedure: ProcedureInfo): string {
  if (procedure.permissions === 'public') {
    return 'Public, requires no permissions.'
  }

  return `Requires "${procedure.permissions}" access permission.`
}

const permissionRank: Record<Exclude<ProcedureInfo['permissions'], 'public'>, number> = {
  view: 0,
  operate: 1,
  manage: 2,
  deny: 3,
}

// Whether the current user's access level meets the procedure's declared minimum.
function canInvoke(procedure: ProcedureInfo): boolean {
  if (procedure.permissions === 'public') {
    return true
  }

  if (effectiveAccess == null) {
    return false
  }

  return permissionRank[effectiveAccess] >= permissionRank[procedure.permissions]
}

// The endpoint rejects callers with no access to the component, in which case the failure is
// expected and simply hides the section.
const configQuery = useQuery({
  queryKey: computed(() => ['component-config', address.toString()]),
  queryFn: () => engine.components.getConfig(address),
  retry: false,
})

const jobsQuery = useQuery({
  queryKey: computed(() => ['component-jobs', address.toString()]),
  queryFn: () => engine.components.getJobs(address),
  retry: false,
})

const connectionsQuery = useQuery({
  queryKey: computed(() => ['component-connections', address.toString()]),
  queryFn: () => engine.components.getConnections(address),
  retry: false,
})

// The statuses stream pushes on lifecycle and connectivity events so a refetch on each push keeps
// connection states and job schedules current without polling. Jobs are included because a
// component's scheduler stops and starts with it, changing each job's next run time.
watch(
  () => engine.statuses.get(address),
  () => {
    void connectionsQuery.refetch()
    void jobsQuery.refetch()
  }
)

const connections = $computed<(ConnectionInfo | ConnectionStateInfo)[]>(
  () => connectionsQuery.data.value ?? component?.connections ?? []
)

const connectivityColors: Record<Connectivity, string> = {
  connected: 'positive',
  connecting: 'warning',
  disconnected: 'negative',
}

const running = $computed(() => engine.statuses.get(address)?.running ?? false)

// A stopped component's connections are expectedly down, shown inert grey rather than alarming
// red, with the pulse stilled to match.
function connectivityColor(connectivity: Connectivity): string {
  return running ? connectivityColors[connectivity] : 'grey'
}

const jobs = $computed(() => jobsQuery.data.value ?? [])

/** Describe a job's schedule and expected next run for display beneath its name. */
function jobLabel(job: JobInfo): string {
  const schedule = `Schedule "${job.schedule}"`
  if (job.next_run == null) {
    return `${schedule}, not scheduled to run.`
  }

  return `${schedule}, next run at ${utc(job.next_run).format('YYYY-MM-DD HH:mm')} UTC.`
}

const configText = $computed(() => {
  const config = configQuery.data.value
  if (config == null) {
    return null
  }

  // Shown as YAML to match how the configuration is written in `ceres.yaml`.
  return stringify(config)
})

const configHighlighted = $computed(() =>
  configText == null ? null : highlight(configText, 'yaml')
)
</script>

<template>
  <full-page fill>
    <template #header-append>
      <common-text class="q-ml-md" variant="title2">
        {{ component?.address?.toString() ?? address.toString() }}
      </common-text>
      <status-badge v-if="component" :address class="q-ml-sm" :scale="0.65" />
      <q-space />
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
      <!-- Flush with the right edge of the widgets below, whose cards sit half a gutter in. -->
      <q-chip
        v-if="effectiveAccess != null"
        class="q-mr-sm q-px-sm"
        color="primary"
        dense
        :icon="icons[effectiveAccess]"
        size="10px"
        text-color="white"
      >
        {{ upperFirst(effectiveAccess) }}
        <q-tooltip class="bg-primary text-white">
          You have permissions to {{ effectiveAccess }} this component.
        </q-tooltip>
      </q-chip>
    </template>

    <div v-if="component == null" class="q-pa-xl text-center text-grey-6">Component not found.</div>
    <template v-else>
      <div v-if="!persisted.overviewCollapsed" ref="overviewElement" class="relative-position">
        <!-- The dragged height only applies while workspace content shows below, and never
        less than what puts the strip at the bottom edge, where it rests until the page is
        scrolled. With workspace content hidden the overview is the page and takes its full
        height. -->
        <div
          :class="[$style.overviewContent, 'scroll']"
          :style="
            activeWorkspaceId != null && !persisted.workspaceCollapsed && !overviewStacks
              ? overviewHeightStyle
              : undefined
          "
        >
          <div :class="[$style.overviewGrid, 'q-col-gutter-md', 'q-pa-md', 'row']">
            <div
              v-if="configHighlighted != null"
              :class="[$style.configColumn, persisted.configuration && $style.configFill]"
            >
              <q-list bordered class="rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.configuration"
                  dense
                  dense-toggle
                  label="Configuration"
                >
                  <!-- eslint-disable-next-line vue/no-v-html -->
                  <pre :class="$style.config"><code v-html="configHighlighted" /></pre>
                </q-expansion-item>
              </q-list>
              <component-workspaces-section
                v-if="workspacesUnderConfig"
                v-model:expanded="persisted.workspaces"
                :can-manage="canManage"
                class="q-mt-md"
                collapsible
                :open-ids="scopedWorkspaces.map((workspace) => workspace.id)"
                :placement="address.toString()"
                :workspaces="placedWorkspaces"
                @close="closeScoped"
                @open="showWorkspace"
                @open-beside="openBesideScoped"
                @share="shareScoped"
              />
            </div>

            <div :class="configHighlighted != null ? $style.detailsColumn : 'col-12'">
              <!-- Workspaces lead the column rather than sitting under the procedure lists, since
              they are what the page is usually opened for and the rest is reference. -->
              <component-workspaces-section
                v-if="!workspacesUnderConfig"
                v-model:expanded="persisted.workspaces"
                :can-manage="canManage"
                class="q-mb-md"
                collapsible
                :open-ids="scopedWorkspaces.map((workspace) => workspace.id)"
                :placement="address.toString()"
                :workspaces="placedWorkspaces"
                @close="closeScoped"
                @open="showWorkspace"
                @open-beside="openBesideScoped"
                @share="shareScoped"
              />

              <q-list bordered class="rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.connections"
                  dense
                  dense-toggle
                  :label="`Connections (${connections.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="connections.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No connections.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item
                      v-for="connection in connections"
                      :key="connection.name"
                      :class="$style.item"
                    >
                      <q-item-section>
                        <q-item-label>{{ connection.name }}</q-item-label>
                        <q-item-label caption>{{ connection.label }}</q-item-label>
                      </q-item-section>
                      <q-item-section v-if="'connectivity' in connection" side>
                        <span
                          :class="[
                            $style.dot,
                            !running && $style.still,
                            `bg-${connectivityColor(connection.connectivity)}`,
                          ]"
                        >
                          <q-tooltip :class="`bg-${connectivityColor(connection.connectivity)}`">
                            {{ upperFirst(connection.connectivity) }}
                          </q-tooltip>
                        </span>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
                <q-separator />
                <q-expansion-item
                  v-model="persisted.jobs"
                  dense
                  dense-toggle
                  :label="`Jobs (${jobs.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="jobs.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No jobs.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="job in jobs" :key="job.name" :class="$style.item">
                      <q-item-section>
                        <q-item-label>{{ job.name }}</q-item-label>
                        <q-item-label caption>{{ jobLabel(job) }}</q-item-label>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
              </q-list>

              <q-list bordered class="q-mt-md rounded-borders" dense>
                <q-expansion-item
                  v-model="persisted.queries"
                  dense
                  dense-toggle
                  :label="`Queries (${queries.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="queries.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No queries.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="query in queries" :key="query.name">
                      <q-item-section>
                        <q-item-label>{{ query.name }}</q-item-label>
                        <q-item-label caption>{{ permissionsLabel(query) }}</q-item-label>
                      </q-item-section>
                      <q-item-section side>
                        <div class="items-center q-gutter-xs row">
                          <q-chip
                            v-if="query.live"
                            color="green"
                            dense
                            label="live"
                            size="10px"
                            text-color="white"
                          />
                          <q-icon
                            v-if="!canInvoke(query)"
                            class="text-grey-6"
                            :name="icons.locked"
                            size="16px"
                          >
                            <q-tooltip>Not available with your access.</q-tooltip>
                          </q-icon>
                        </div>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
                <q-separator />
                <q-expansion-item
                  v-model="persisted.actions"
                  dense
                  dense-toggle
                  :label="`Actions (${actions.length})`"
                >
                  <q-list class="q-pb-sm" dense>
                    <q-item v-if="actions.length === 0">
                      <q-item-section>
                        <q-item-label class="text-grey-6">No actions.</q-item-label>
                      </q-item-section>
                    </q-item>
                    <q-item v-for="action in actions" :key="action.name">
                      <q-item-section>
                        <q-item-label>{{ action.name }}</q-item-label>
                        <q-item-label caption>{{ permissionsLabel(action) }}</q-item-label>
                      </q-item-section>
                      <q-item-section v-if="!canInvoke(action)" side>
                        <q-icon class="text-grey-6" :name="icons.locked" size="16px">
                          <q-tooltip>Not available with your access.</q-tooltip>
                        </q-icon>
                      </q-item-section>
                    </q-item>
                  </q-list>
                </q-expansion-item>
              </q-list>

              <component-particles-section
                v-model:expanded="persisted.particles"
                v-model:expanded-types="persisted.particleTypes"
                :address
                :insert-at="workspacePageRef?.insertWidgetsAt"
                :insert-drag="workspacePageRef?.startInsertDrag"
                @create="createWidgetsScoped"
              />

              <div v-if="component.tags.length > 0" class="q-mt-md">
                <div class="q-mb-xs text-subtitle2">Tags</div>
                <div class="q-gutter-xs row">
                  <q-chip
                    v-for="tag in component.tags"
                    :key="tag"
                    dense
                    :label="tag"
                    outline
                    size="sm"
                  />
                </div>
              </div>
            </div>

            <div v-if="component.components.length > 0" class="col-12">
              <div class="q-mb-xs text-subtitle2">Subcomponents</div>
              <q-list bordered class="rounded-borders" dense separator>
                <q-item
                  v-for="child in component.components"
                  :key="child.name"
                  clickable
                  :to="`/components/${child.address}`"
                >
                  <q-item-section>
                    <q-item-label>{{ child.name }}</q-item-label>
                    <q-item-label caption>{{ child.address }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <status-badge :address="new Address(child.address.toString())" />
                  </q-item-section>
                </q-item>
              </q-list>
            </div>
          </div>
        </div>
        <resize-handle
          v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed && !overviewStacks"
          v-model="persisted.overviewHeight"
          :class="$style.overviewResizeHandle"
          direction="vertical"
          :max="800"
          :min="120"
        />
      </div>
      <!-- The strip sits in flow between the overview and the workspace, and sticks at both
      edges so it is always on screen, pinning under the header the way it always has and
      resting at the bottom while its own place is still below the fold. -->
      <component-workspace-strip
        v-if="scopedWorkspaces.length > 0 || canCreate"
        ref="stripRef"
        v-model:collapsed="persisted.workspaceCollapsed"
        :sticky-top="workspaceStickyTop"
      >
        <template #default="{ docked, trailingInset }">
          <component-workspace-tabs
            :active="activeWorkspaceId"
            :active-actions="workspacePageRef?.headerActions"
            :active-state="workspacePageRef?.headerState"
            bound
            :can-create="canCreate"
            :can-manage="canManage"
            :docked="docked"
            :openable="openableWorkspaces"
            :trailing-inset="trailingInset"
            :workspaces="scopedWorkspaces"
            @close="closeScoped"
            @close-all="closeAllScoped"
            @close-others="closeOtherScoped"
            @create="createScoped"
            @import="importScoped"
            @open="openScoped"
            @open-all="openAllScoped"
            @open-beside="openBesideScoped"
            @reorder="reorderScoped"
            @select="revealScoped"
            @share="shareScoped"
          />
        </template>
      </component-workspace-strip>
      <!-- Deliberately not keyed on the workspace ID, so switching tabs updates this page in
      place. -->
      <workspace-page
        v-if="activeWorkspaceId != null && !persisted.workspaceCollapsed"
        :id="activeWorkspaceId"
        ref="workspacePageRef"
        :sticky-top="workspaceStickyTop"
        :strip-docked="stripDocked"
        @duplicated="openBesideScoped"
      />
    </template>
  </full-page>
</template>

<style lang="scss" module>
// The config and connections blocks sit side by side above this width and stack below it.
$overview-columns-min: 720px;

// With a workspace below, the panel takes the height dragged onto it, set inline. On its own it
// grows with its content up to what is left of the viewport, then scrolls. This is a maximum
// rather than a fixed height so a collapsed configuration does not leave the panel padded out
// with empty space down to the fold.
.overviewContent {
  overflow-x: hidden;
  max-height: calc(100vh - 92px);
}

// The grid fills the panel so the configuration can reach its bottom edge, and grows past it
// when the other column is taller.
.overviewGrid {
  min-height: 100%;
}

.configColumn,
.detailsColumn {
  flex: 0 0 100%;
  max-width: 100%;
}

// An expanded configuration stretches to the bottom of the panel and scrolls its own contents.
.configFill {
  display: flex;
  flex-direction: column;
  min-height: 0;

  > :global(.q-list),
  :global(.q-expansion-item),
  :global(.q-expansion-item__container) {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-height: 0;
  }

  :global(.q-expansion-item__content) {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
}

@media (min-width: $overview-columns-min) {
  .configColumn {
    flex-basis: 41.6667%;
    max-width: 41.6667%;
  }

  .detailsColumn {
    flex-basis: 58.3333%;
    max-width: 58.3333%;
  }
}

.overviewResizeHandle {
  position: absolute;
  bottom: 0;
  left: 0;
}

.item {
  padding-top: 6px;
  padding-bottom: 6px;
}

.config {
  margin: 0;
  overflow-x: auto;
  padding: 8px 12px 12px;
  font-size: 12px;
  line-height: 1.5;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

.still {
  animation: none;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.65;
  }
}
</style>
